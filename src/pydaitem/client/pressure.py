"""What the client sends, and when it should not send anything: counters and a breaker.

Every request reaches the Daitem servers, shared by every client of every user. The counters
make that cost visible to a host (its diagnostics, its logs). The breaker stops sending when
the API says it is overloaded, rather than adding to it.
"""

from __future__ import annotations

import logging
import random
import re
import time
from collections import Counter
from dataclasses import dataclass, field

from ..exceptions import DaitemApiError, DaitemRateLimitedError

_LOGGER = logging.getLogger(__name__)

#: Statuses a gateway answers when the service behind it is down or overloaded.
_GATEWAY_STATUSES = frozenset({502, 503, 504})

#: How many gateway errors in a row open the breaker. A rate limit opens it at once.
GATEWAY_FAILURES = 3

#: The first pause, then doubled at each new refusal, up to the cap.
FIRST_PAUSE = 5.0
MAX_PAUSE = 300.0

_ID_SEGMENT = re.compile(r"/\d+(?=/|$)")


def endpoint(method: str, path: str) -> str:
    """`method path` with ids written `{id}`, so calls to one endpoint count together."""
    return f"{method} {_ID_SEGMENT.sub('/{id}', path)}"


@dataclass(slots=True)
class ClientStats:
    """What a client sent since it was created. Read it from `DaitemClient.stats`."""

    requests: Counter[str] = field(default_factory=Counter)
    """Requests that left, by endpoint (`GET /topaze/v5/systems/{id}/state`), retries included."""
    retries: int = 0
    """Requests sent again after a dropped connection."""
    refused_locally: int = 0
    """Calls the breaker answered itself, without the network."""
    sessions_opened: int = 0
    session_seconds: float = 0.0
    """How long panel sessions were held in all: the time the mobile app was kept out."""

    @property
    def total_requests(self) -> int:
        return sum(self.requests.values())

    def copy(self) -> ClientStats:
        return ClientStats(
            requests=Counter(self.requests),
            retries=self.retries,
            refused_locally=self.refused_locally,
            sessions_opened=self.sessions_opened,
            session_seconds=self.session_seconds,
        )


class _Breaker:
    """Stop sending for a while when the API says it is overloaded.

    Opens on a rate limit (`DaitemRateLimitedError`) or after `GATEWAY_FAILURES` gateway
    errors in a row, for `FIRST_PAUSE` seconds, doubled at each new refusal up to
    `MAX_PAUSE`, with a fifth of jitter so clients do not come back in step. Once the pause
    is over requests go through again, and the first success closes it. An HTTP 500 does
    not count: the API sends business errors (a wrong code) with it.
    """

    def __init__(self) -> None:
        self.open_until = 0.0
        self._pause = 0.0
        self._gateway_failures = 0

    def remaining(self) -> float:
        """Seconds the breaker stays open, 0 when requests may go."""
        return max(self.open_until - time.monotonic(), 0.0)

    def succeeded(self) -> None:
        self._pause = 0.0
        self._gateway_failures = 0

    def failed(self, err: DaitemApiError) -> None:
        if isinstance(err, DaitemRateLimitedError):
            self._trip(str(err))
        elif type(err) is DaitemApiError and err.status in _GATEWAY_STATUSES:
            self._gateway_failures += 1
            if self._gateway_failures >= GATEWAY_FAILURES:
                self._trip(f"{self._gateway_failures} gateway errors in a row ({err.status})")

    def _trip(self, reason: str) -> None:
        self._pause = FIRST_PAUSE if not self._pause else min(self._pause * 2, MAX_PAUSE)
        pause = self._pause * random.uniform(0.8, 1.2)
        self.open_until = time.monotonic() + pause
        self._gateway_failures = 0
        _LOGGER.warning(
            "The Daitem API asked to back off (%s): no request for %.0f s", reason, pause
        )
