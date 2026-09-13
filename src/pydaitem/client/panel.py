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
import time
from collections.abc import AsyncIterator

from ..exceptions import DaitemError, DaitemNoSessionError
from ..models import SystemStatus
from .state import _ClientState
from .transport import _Transport

_LOGGER = logging.getLogger(__name__)


class _Panel:
    def __init__(self, state: _ClientState, transport: _Transport) -> None:
        self._state = state
        self._transport = transport

    @property
    def ttm_session_id(self) -> str | None:
        return self._state.ttm_session_id

    async def connect(self, system_id: int, master_code: str) -> SystemStatus:
        """Open the panel session. Raises DaitemSessionBusyError if already taken."""
        data = await self._transport.request(
            "POST", f"/topaze/v5/systems/{system_id}/connect", json={"masterCode": master_code}
        )
        self._state.ttm_session_id = data.get("ttmSessionId")
        return SystemStatus.from_json(data)

    async def disconnect(self, system_id: int, *, force: bool = False) -> None:
        await self._transport.request(
            "POST", f"/topaze/v5/systems/{system_id}/disconnect", json={"force": force}
        )
        self._state.ttm_session_id = None

    async def keep_alive(self) -> None:
        """Keep the session alive. Optional: polling the state is enough."""
        if not self._state.ttm_session_id:
            raise DaitemNoSessionError("keep_alive without an open session")
        await self._transport.request(
            "POST",
            "/topaze/authenticate/keepAlive",
            json={"ttmSessionId": self._state.ttm_session_id},
        )

    @contextlib.asynccontextmanager
    async def session(self, system_id: int, master_code: str) -> AsyncIterator[SystemStatus]:
        """Hold a session for the duration of the block, then always release it.

        Use it for every command and every read cycle: the panel accepts a single session
        at a time, so it must be freed quickly.
        """
        status = await self.connect(system_id, master_code)
        try:
            yield status
        finally:
            try:
                await self.disconnect(system_id)
            except DaitemError as err:
                # A leaked session is what a later DaitemSessionBusyError will look like,
                # so make the cause traceable.
                _LOGGER.debug("Could not release the panel session for %s: %s", system_id, err)

    async def get_state(self, system_id: int) -> SystemStatus:
        """Read the state. Raises DaitemNoSessionError if no session is usable."""
        data = await self._transport.request("GET", f"/topaze/v5/systems/{system_id}/state")
        return SystemStatus.from_json(data)

    async def get_status(self, system_id: int, master_code: str) -> SystemStatus:
        """Opportunistic read, the recommended strategy.

        Try a direct read first: if another device (the mobile app, typically) already
        holds a session, we piggyback on it without disturbing anything. Only otherwise do
        we open a session, read, and release it.
        """
        try:
            return await self.get_state(system_id)
        except DaitemNoSessionError:
            async with self.session(system_id, master_code):
                return await self.get_state(system_id)

    async def wait_for_stable_state(
        self, system_id: int, *, timeout: float = 120.0, interval: float = 2.0
    ) -> SystemStatus:
        """Poll until an arming delay (`tempo`/`tempogroup`) has elapsed."""
        deadline = time.monotonic() + timeout
        status = await self.get_state(system_id)
        while status.is_arming and time.monotonic() < deadline:
            await asyncio.sleep(interval)
            status = await self.get_state(system_id)
        return status
