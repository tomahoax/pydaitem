"""Panel state and connectivity: `system.panel.*`."""

from __future__ import annotations

import asyncio
import time

from ..exceptions import DaitemApiError, DaitemNoSessionError
from ..models import SystemStatus
from ..models._shared import find_key
from .state import _SystemState, bounded


class _Panel:
    def __init__(self, state: _SystemState) -> None:
        self._state = state
        self._transmitter_id: str | None = None

    @bounded("panel.read")
    async def read(self, *, max_age: float = 0.0) -> SystemStatus:
        """Read the state, opening a session only if none is usable.

        Another device's session (the mobile app's, typically) is used as it is, so a read
        does not disturb it. Opens a session otherwise, so may raise the session errors.
        """
        state = self._state
        kept: SystemStatus | None = state.kept("panel.read", max_age)
        if kept is not None:
            return kept
        status = await state.shared("panel.read", self._read)
        state.keep("panel.read", status)
        return status

    async def _read(self) -> SystemStatus:
        state = self._state
        try:
            return await state.client.panel.get_state(state.system_id)
        except DaitemNoSessionError:
            # As `client.panel.get_status`, plus whatever is waiting for a session.
            async with state.session() as status:
                if state.in_read_session is not None:
                    await state.in_read_session()
                return status

    @bounded("panel.check_code")
    async def check_code(self) -> None:
        """Open a panel session with the code, then release it at once.

        For a setup form that wants to know the code works before saving it. Raises
        `DaitemBadCodeError` when the panel refuses it. Raises `DaitemSessionBusyError` when
        another device holds the panel, and then the code is left unchecked: ask the user to
        close the mobile app and try again. The panel is held for the length of one connect.
        """
        async with self._state.session():
            pass

    async def wait_settled(self, *, timeout: float = 120.0, interval: float = 2.0) -> SystemStatus:
        """Read the state until no exit delay runs, or `timeout` seconds have passed.

        Returns the last state read, which is still `ARMING` when the delay outlasts
        `timeout`. Each read may open a short panel session when no other device holds one,
        so may raise the session errors, as `read()` does.
        """
        deadline = time.monotonic() + timeout
        status = await self.read()
        while status.is_arming and time.monotonic() < deadline:
            await asyncio.sleep(interval)
            status = await self.read()
        return status

    @bounded("panel.transmitter_online")
    async def transmitter_online(self) -> bool | None:
        """Whether the transmitter, and so the panel, can be reached. Needs no panel session.

        None when the API does not say. The transmitter id is read once, from the
        installation record, then kept. Raises `DaitemApiError` when the record gives none.
        """
        state = self._state
        if self._transmitter_id is None:
            self._transmitter_id = await self._read_transmitter_id()
        return await state.client.panel.is_connected(self._transmitter_id)

    async def _read_transmitter_id(self) -> str:
        """The installation record carries it, read with the account's role as the app does."""
        state = self._state
        systems = await state.client.account.list_systems()
        role = next((s.role for s in systems if s.id == state.system_id), None)
        record = await state.client.devices.get_configuration(state.system_id, role)
        # Look for the id at any depth, as `collect_raw` does.
        transmitter = find_key(record, "transmitterId")
        if not transmitter:
            raise DaitemApiError("the installation record gives no transmitter id")
        return str(transmitter)
