"""Shared, mutable state: config, tokens, and the underlying `aiohttp` session.

Every service (`_Auth`, `_Transport`, `_Panel`, ...) is handed this same instance, so a token
refreshed by `_Auth` is immediately visible to `_Transport`, and a panel session opened by
`_Panel` is visible everywhere without any service reaching into another.
"""

from __future__ import annotations

import asyncio

import aiohttp
from yarl import URL

from ..const import REALM
from ..exceptions import DaitemUsageError
from ..tokens import TokenStore
from .pressure import ClientStats, _Breaker


class _ClientState:
    def __init__(
        self,
        email: str,
        password: str,
        *,
        session: aiohttp.ClientSession | None,
        api_base: str,
        auth_base: str,
        timeout: float,
        token_store: TokenStore | None,
        call_timeout: float | None = None,
        max_session_hold: float | None = None,
    ) -> None:
        self.email = email
        self.password = password
        self.api_base = _secure(api_base)
        self.auth_base = _secure(auth_base)
        # An address that does not answer at all fails on the connect timeout, without
        # cutting short a slow answer that is still coming.
        self.timeout = aiohttp.ClientTimeout(total=timeout, sock_connect=min(timeout, 10.0))
        self.call_timeout = call_timeout
        self.max_session_hold = max_session_hold
        self.stats = ClientStats()
        self.breaker = _Breaker()
        # Endpoints whose cache headers were logged already: once each is enough.
        self.cache_headers_seen: set[str] = set()
        self.session = session
        self.owns_session = session is None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expires_at: float = 0.0
        self.auth_lock = asyncio.Lock()
        self.token_store = token_store
        self.store_loaded = False
        self.ttm_session_id: str | None = None
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        if self.owns_session and self.session is not None:
            await self.session.close()
            self.session = None

    def ensure_session(self) -> aiohttp.ClientSession:
        if self.closed:
            # A request still running when the client was closed must not open an HTTP
            # session that nothing would ever close.
            raise DaitemUsageError("the client is closed")
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            self.owns_session = True
        return self.session

    @property
    def token_url(self) -> str:
        return f"{self.auth_base}/realms/{REALM}/protocol/openid-connect/token"


#: Hosts allowed over plain http, for a local test server only.
_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _secure(base: str) -> str:
    """`base` without its trailing slash, refused unless it is https.

    The password, the tokens and the alarm code all travel to these addresses.
    """
    url = URL(base)
    if url.scheme != "https" and url.host not in _LOCAL_HOSTS:
        raise ValueError(f"{base!r} is not an https address")
    return base.rstrip("/")
