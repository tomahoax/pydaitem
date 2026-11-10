"""Panel session and state: `client.panel.*`.

The panel accepts a single session at a time, across all accounts; a concurrent `connect`
returns 409. `session()` holds one for the duration of a block and always releases it, and
`get_status()` tries a direct read first so it can piggyback on a session already held by
another device (typically the mobile app) instead of disturbing it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import AsyncIterator
from typing import Any

from ..exceptions import (
    DaitemApiError,
    DaitemConnectionError,
    DaitemError,
    DaitemNoSessionError,
    DaitemUsageError,
    Remedy,
)
from ..models import SystemStatus
from ..models._shared import parse
from . import trace
from .jobs import JOB_ID, job_path, poll_job
from .paths import segment
from .state import _ClientState
from .transport import KEEP_ALIVE_PATH, _Transport

_LOGGER = logging.getLogger(__name__)

#: How long an asynchronous connect may take, and how often it is polled meanwhile.
CONNECT_POLL_TIMEOUT = 30.0
CONNECT_POLL_INTERVAL = 1.0

#: How long releasing the panel may take once the caller has stopped waiting for it.
RELEASE_TIMEOUT = 10.0

#: Shape of the poll path of an asynchronous connect. Enforced so a `Location` header cannot
#: redirect the authenticated request to an arbitrary endpoint on `api_base`.
_CONNECT_POLL_RE = re.compile(rf"/topaze/v5/systems/\d+/connect/{JOB_ID}")


class _Panel:
    def __init__(self, state: _ClientState, transport: _Transport) -> None:
        self._state = state
        self._transport = transport
        # One session at a time from this client: the panel would refuse a second one with
        # 409, which callers would mistake for another device holding it.
        self._lock = asyncio.Lock()
        self._owner: asyncio.Task[Any] | None = None
        self._releases: set[asyncio.Task[None]] = set()

    @property
    def ttm_session_id(self) -> str | None:
        return self._state.ttm_session_id

    async def connect(self, system_id: int, master_code: str) -> SystemStatus:
        """Open the panel session. Raises DaitemSessionBusyError if already taken.

        The panel usually answers at once. The app also handles a deferred answer, polled
        on `connect/{transactionId}` until it is done, and so does this method: see
        `_await_connect`.
        """
        # Never replayed: if the panel opened the session and only its answer was lost, a
        # replay would meet that session and report it as held by someone else.
        try:
            data, headers = await self._transport.request_full(
                "POST",
                f"/topaze/v5/systems/{system_id}/connect",
                json={"masterCode": master_code},
                retry=False,
            )
        except BaseException as err:
            # An error answer means the panel refused, so nothing is open. A lost answer or a
            # cancelled caller may leave a session open that nobody would release.
            if not isinstance(err, DaitemError) or isinstance(err, DaitemConnectionError):
                await self._release(system_id)
            if isinstance(err, DaitemConnectionError):
                # Released above, so nothing is left to check: opening again later is safe.
                err.remedy = Remedy.RETRY_LATER
            raise
        try:
            if not isinstance(data, dict):
                raise DaitemApiError(
                    f"POST /topaze/v5/systems/{system_id}/connect: expected a JSON object, "
                    f"got {type(data).__name__}"
                )
            location = headers.get("Location")
            if not data.get("ttmSessionId") and location:
                data = await self._await_connect(system_id, location)
            self._state.ttm_session_id = data.get("ttmSessionId")
            return parse(lambda: SystemStatus.from_json(data), "connect")
        except BaseException:
            # The panel accepted the request: whatever went wrong since, the session may be
            # open, so release it rather than lock everyone out until it expires.
            await self._release(system_id)
            raise

    async def _await_connect(self, system_id: int, location: str) -> dict[str, Any]:
        """Poll a deferred connect until the panel has answered, and return that answer.

        The job follows the same shape as the logbook job (see `jobs.py`).
        """
        path = job_path(location, _CONNECT_POLL_RE, "connect poll", system_id=system_id)
        response = await poll_job(
            self._transport,
            path,
            timeout=CONNECT_POLL_TIMEOUT,
            interval=CONNECT_POLL_INTERVAL,
            what="connect",
        )
        return response if isinstance(response, dict) else {}

    async def disconnect(self, system_id: int, *, force: bool = False) -> None:
        try:
            await self._transport.request(
                "POST",
                f"/topaze/v5/systems/{system_id}/disconnect",
                json={"force": force},
                guarded=False,  # a release always goes out, breaker open or not
            )
        finally:
            # Even when the answer is lost: a stale id would only make keep_alive lie.
            self._state.ttm_session_id = None

    async def _release(self, system_id: int) -> None:
        """Disconnect, never raising, and even when the caller is cancelled meanwhile.

        The disconnect runs in its own task, shielded: a caller cancelled again (a timeout,
        a shutdown) gets its `CancelledError` while the release still completes.
        """
        task = asyncio.ensure_future(self._disconnect_quietly(system_id))
        self._releases.add(task)
        task.add_done_callback(self._releases.discard)
        await asyncio.shield(task)

    async def _disconnect_quietly(self, system_id: int) -> None:
        try:
            async with asyncio.timeout(RELEASE_TIMEOUT):
                await self.disconnect(system_id)
        except Exception as err:
            # A leaked session is what a later DaitemSessionBusyError will look like, so make
            # the cause traceable.
            _LOGGER.debug("Could not release the panel session for %s: %s", system_id, err)

    def _watch(self, system_id: int, trace_id: str) -> asyncio.TimerHandle | None:
        """Free the panel if the block outlives `max_session_hold`, whoever holds it.

        The mobile app cannot connect while the session is open, so one block left open by
        mistake, or stuck on a hung server, must not lock it out for good. The block's own
        calls fail afterwards, as on a lost session, and the panel is released once more on
        its way out, which does no harm.
        """
        hold = self._state.max_session_hold
        if hold is None:
            return None

        def overheld() -> None:
            _LOGGER.warning(
                "Panel session %s held for more than %g s: releasing it for the other devices",
                trace_id,
                hold,
            )
            task = asyncio.ensure_future(self._disconnect_quietly(system_id))
            self._releases.add(task)
            task.add_done_callback(self._releases.discard)

        return asyncio.get_running_loop().call_later(hold, overheld)

    def _release_later(self, system_id: int, trace_id: str, opened: float) -> None:
        """Disconnect in a task of its own, then hand the panel lock on.

        The caller already has its answer, so the release costs it no round trip. The lock
        stays held until the panel is free: the next session on this client never meets its
        own leftover as a 409, and `close()` waits for it (`wait_released`). Created rather
        than awaited, it cannot be cut short by a caller cancelled meanwhile.
        """

        async def release() -> None:
            try:
                await self._disconnect_quietly(system_id)
                self._state.stats.session_seconds += time.monotonic() - opened
                # How long the panel was kept from every other device, the mobile app
                # included: the figure to look at when it reports the panel busy.
                _LOGGER.debug(
                    "Panel session %s: released, held %s ms", trace_id, trace.elapsed_ms(opened)
                )
            finally:
                self._lock.release()

        task = asyncio.ensure_future(release())
        self._releases.add(task)
        task.add_done_callback(self._releases.discard)

    async def wait_released(self) -> None:
        """Wait until every panel session this client opened is released.

        A session block hands its release to a task and returns at once: call this to know
        the panel is free, before a test asserts it or a process exits.
        """
        if self._releases:
            await asyncio.gather(*self._releases, return_exceptions=True)

    async def keep_alive(self) -> None:
        """Keep the session alive. Optional: polling the state is enough."""
        if not self._state.ttm_session_id:
            raise DaitemNoSessionError("keep_alive without an open session")
        await self._transport.request(
            "POST",
            KEEP_ALIVE_PATH,
            json={"ttmSessionId": self._state.ttm_session_id},
        )

    @contextlib.asynccontextmanager
    async def session(self, system_id: int, master_code: str) -> AsyncIterator[SystemStatus]:
        """Hold a session for the duration of the block, then always release it.

        Use it for every command and every read cycle: the panel accepts a single session
        at a time, so it must be freed quickly. Concurrent blocks on one client wait for each
        other. A block cannot open a second session inside itself: that raises
        DaitemUsageError instead of waiting forever.
        """
        task = asyncio.current_task()
        if task is not None and task is self._owner:
            raise DaitemUsageError("a panel session is already open in this task")
        await self._lock.acquire()
        handed_over = False
        self._owner = task
        trace_id, token = trace.begin()
        try:
            started = time.monotonic()
            _LOGGER.debug("Panel session %s: opening on system %s", trace_id, system_id)
            status = await self.connect(system_id, master_code)
            opened = time.monotonic()
            self._state.stats.sessions_opened += 1
            _LOGGER.debug("Panel session %s: open in %s ms", trace_id, trace.elapsed_ms(started))
            watchdog = self._watch(system_id, trace_id)
            try:
                yield status
            finally:
                if watchdog is not None:
                    watchdog.cancel()
                self._owner = None
                # The lock goes with the release: the task hands it on once the panel is free.
                self._release_later(system_id, trace_id, opened)
                handed_over = True
        finally:
            if not handed_over:
                self._owner = None
                self._lock.release()
            trace.end(token)

    async def is_connected(self, transmitter_id: str) -> bool | None:
        """Whether the transmitter is online. Needs no panel session.

        `transmitter_id` comes from `client.devices.get_configuration`. None when the answer
        does not say.
        """
        data = await self._transport.request(
            "POST", "/topaze/installation/isConnected", json={"transmitterId": transmitter_id}
        )
        value = data.get("isConnected") if isinstance(data, dict) else None
        return value if isinstance(value, bool) else None

    async def switch_mode(self, system_id: int, mode: str) -> None:
        """WARNING: puts the panel in installation, test or usage mode (`PanelMode`).

        Installer territory: in installation or test mode the alarm does not protect.
        """
        await self._transport.request(
            "POST", f"/topaze/v5/systems/{system_id}/switchMode/{segment(mode)}", retry=False
        )

    async def get_state(self, system_id: int) -> SystemStatus:
        """Read the state. Raises DaitemNoSessionError if no session is usable."""
        data = await self._transport.request_object("GET", f"/topaze/v5/systems/{system_id}/state")
        return parse(lambda: SystemStatus.from_json(data), "state")

    async def get_status(self, system_id: int, master_code: str) -> SystemStatus:
        """Opportunistic read, the recommended strategy.

        Try a direct read first: if another device (the mobile app, typically) already
        holds a session, we piggyback on it without disturbing anything. Only otherwise do
        we open a session, read, and release it.
        """
        try:
            return await self.get_state(system_id)
        except DaitemNoSessionError:
            # Connect answers with the state: reading it again would only cost a round trip
            # while the panel is held.
            async with self.session(system_id, master_code) as status:
                return status
