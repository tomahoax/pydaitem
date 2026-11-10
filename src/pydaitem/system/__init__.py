"""High-level façade bound to one installation.

This is the surface consumers should use. It hides everything that can change on the
Daitem side: endpoints, the session protocol, preset indices and group identifiers. A
change in the API signature is absorbed here or in `const`, never by the caller.

    async with DaitemClient(email, password) as client:
        system = DaitemSystem(client, system_id, alarm_code)
        status = await system.panel.read()
        await system.commands.arm_away()

Grouped like the API itself, one namespace per resource: `system.panel`,
`system.inventory`, `system.commands`, `system.schedule`, `system.automation`,
`system.scenarios`, `system.video` and `system.logbook`, plus `system.capabilities` for
what the installation supports. Method names are the façade's own (`read`, `cameras`,
`clips`...), not the client's. Only what spans several resources stays on `DaitemSystem`:
`read_extras` and `collect_raw`.

WARNING: `system.commands.*` and `system.scenarios.run` drive a real alarm,
`system.automation.command` real equipment such as a gate.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from typing import Any

import aiohttp

from ..client import DaitemClient
from ..exceptions import DaitemUsageError
from ..tokens import TokenStore
from .automation import _Automation
from .capabilities import _Capabilities
from .commands import _Commands
from .extras import Extras, read_extras
from .inventory import _Inventory
from .logbook import _Logbook
from .panel import _Panel
from .probe import collect_raw
from .scenarios import _Scenarios
from .schedule import _Schedule
from .snapshot import Snapshot, read_snapshot
from .state import _SystemState
from .video import _Video

__all__ = ["DaitemSystem", "Extras", "Snapshot", "connect"]


class DaitemSystem:
    """One Daitem installation, driven through semantic operations.

    Errors. Any call may raise `DaitemConnectionError`, `DaitemAuthError`,
    `DaitemTransmitterOfflineError`, `DaitemRateLimitedError` or a plain `DaitemApiError`.
    A call that opens a panel session may also raise the session errors:
    `DaitemSessionBusyError` (another device holds the panel), `DaitemBadCodeError` (the
    panel refused the code) and `DaitemSessionRestrictedError`. Each method says whether it
    opens a session, and which other errors are its own. Nothing outside `DaitemError`
    escapes, except `asyncio.CancelledError`.
    """

    def __init__(self, client: DaitemClient, system_id: int, code: str) -> None:
        """`code` is the alarm code of the account in use, not necessarily the master."""
        self._state = _SystemState(client, system_id, code)
        self.panel = _Panel(self._state)
        self.inventory = _Inventory(self._state)
        self.capabilities = _Capabilities(self._state)
        self.commands = _Commands(self._state, self.capabilities)
        self._state.in_read_session = self.capabilities._discover_if_wanted
        self.schedule = _Schedule(self._state)
        self.automation = _Automation(self._state)
        self.video = _Video(self._state)
        self.logbook = _Logbook(self._state)
        self.scenarios = _Scenarios(self._state)

    @property
    def system_id(self) -> int:
        return self._state.system_id

    @property
    def client(self) -> DaitemClient:
        """The low-level client underneath, for calls the façade does not cover.

        Not part of the stable contract: its methods mirror the API one for one.
        """
        return self._state.client

    # -- Reads across resources ---------------------------------------------------

    async def read_snapshot(self) -> Snapshot:
        """The state and the inventory, what a poll cycle reads, in one call.

        Each read fails on its own: its field stays None and its error lands in
        `Snapshot.errors`, so a busy panel does not hide the faults, which need no session.
        Never raises a `DaitemError`. The state read may open a short panel session.
        """
        return await read_snapshot(self)

    async def read_extras(self) -> Extras:
        """Automations, cameras and clips, with at most one panel session for all three.

        A read that fails leaves its list None and its error in `Extras.errors`, so one
        missing right (videos, typically) does not hide the others. Never raises a
        `DaitemError`: every failure, session errors included, lands in `Extras.errors`.
        """
        return await read_extras(self._state)

    async def collect_raw(self, *, logbook_entries: int = 5, redact: bool = True) -> dict[str, Any]:
        """Raw answers of every read that matters to an integration, for diagnostics.

        See `probe.collect_raw`. Redacted by default with `pydaitem.redact`: secrets go,
        identifiers keep their ends. `redact=False` keeps the personal data as sent.
        """
        return await collect_raw(self, logbook_entries=logbook_entries, redact=redact)


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
    Raises `DaitemAuthError` when the account is refused, and `DaitemUsageError` when it has
    no installation. The alarm code is only checked by the first call that opens a panel
    session.

        async with connect(email, password, code) as system:
            print((await system.panel.read()).panel_state)

    Pass `system_id` explicitly when the account holds several installations, and
    `session` to reuse an existing aiohttp session rather than opening one.
    """
    client = DaitemClient(email, password, session=session, token_store=token_store)
    try:
        if system_id is None:
            systems = await client.account.list_systems()
            if not systems:
                raise DaitemUsageError("this account has no installation")
            system_id = systems[0].id
        yield DaitemSystem(client, system_id, code)
    finally:
        await client.close()
