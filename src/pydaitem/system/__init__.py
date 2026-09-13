"""High-level façade bound to one installation.

This is the surface consumers should use. It hides everything that can change on the
Daitem side: endpoints, the session protocol, preset indices and group identifiers. A
change in the API signature is absorbed here or in `const`, never by the caller.

    async with DaitemClient(email, password) as client:
        system = DaitemSystem(client, system_id, alarm_code)
        status = await system.read_status()
        await system.commands.arm_away()

Grouped by resource, like `DaitemClient`: `system.capabilities`, `system.commands`,
`system.schedule`. Reads that need no shared state (`read_status`, `read_inventory`) stay
directly on `DaitemSystem`.

WARNING: `system.commands.*` drives a real alarm.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator

import aiohttp

from ..client import DaitemClient
from ..exceptions import DaitemError
from ..models import Inventory, SystemStatus
from ..tokens import TokenStore
from .capabilities import _Capabilities
from .commands import _Commands
from .schedule import _Schedule
from .state import _SystemState

__all__ = ["DaitemSystem", "connect"]


class DaitemSystem:
    """One Daitem installation, driven through semantic operations."""

    def __init__(self, client: DaitemClient, system_id: int, code: str) -> None:
        """`code` is the alarm code of the account in use, not necessarily the master."""
        self._state = _SystemState(client, system_id, code)
        self.capabilities = _Capabilities(self._state)
        self.commands = _Commands(self._state, self.capabilities)
        self.schedule = _Schedule(self._state)

    @property
    def system_id(self) -> int:
        return self._state.system_id

    # -- Reads -------------------------------------------------------------------

    async def read_status(self) -> SystemStatus:
        """Read the state, opening a session only if none is usable."""
        return await self._state.client.panel.get_status(self._state.system_id, self._state.code)

    async def read_inventory(self) -> Inventory:
        """Read the device inventory, including current faults.

        Needs no panel session, so it is safe to call on every poll cycle. Faults live
        here, so refreshing it is what keeps fault reporting alive.
        """
        return await self._state.client.account.get_inventory(self._state.system_id)


@contextlib.asynccontextmanager
async def connect(
    email: str,
    password: str,
    code: str,
    *,
    system_id: int | None = None,
    token_store: TokenStore | None = None,
    session: aiohttp.ClientSession | None = None,
) -> AsyncIterator[DaitemSystem]:
    """Open a ready-to-use system in one step.

    Handles the client lifecycle and picks the account's first installation when
    `system_id` is omitted, so callers do not have to wire three objects together.

        async with connect(email, password, code) as system:
            print((await system.read_status()).panel_state)

    Pass `system_id` explicitly when the account holds several installations, and
    `session` to reuse an existing aiohttp session rather than opening one.
    """
    client = DaitemClient(email, password, session=session, token_store=token_store)
    try:
        if system_id is None:
            systems = await client.account.list_systems()
            if not systems:
                raise DaitemError("this account has no installation")
            system_id = systems[0].id
        yield DaitemSystem(client, system_id, code)
    finally:
        await client.close()
