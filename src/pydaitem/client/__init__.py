"""Async client for the private Daitem Secure API.

Depends only on `aiohttp`.

Design notes:

- Authentication uses OAuth2 **authorization_code + PKCE**. The Keycloak realm refuses the
  `password` grant, so it is not implemented.
- The panel accepts **a single session at a time**, across all accounts; a concurrent
  `connect` returns 409. Hence `panel.session()`, which releases as soon as possible, and
  `panel.get_status()`, which reads without opening a session when it can.
- Reading the state requires a session to exist, held by any device.

Every call of the app's API has a method, grouped by resource: `account`, `panel`,
`commands`, `schedule`, `logbook`, `widgets`, `automation`, `video`, `scenarios`,
`devices`, `notifications`, `users`. They mirror the API one for one, so they are not part
of the stable contract: `DaitemSystem` is.

WARNING: `commands.*`, `automation.command()`, the writes of `schedule`, `scenarios`,
`devices` and `users`, and `panel.switch_mode()` drive a real installation, directly or by
changing how it behaves.
"""

from __future__ import annotations

from typing import Self

import aiohttp

from ..const import API_BASE, AUTH_BASE
from ..tokens import TokenStore
from .account import _Account
from .auth import _Auth
from .automation import _Automation
from .commands import _Commands
from .devices import _Devices
from .logbook import _Logbook
from .notifications import _Notifications
from .panel import _Panel
from .pressure import ClientStats
from .scenarios import _Scenarios
from .schedule import _Schedule
from .state import _ClientState
from .transport import _Transport
from .users import _Users
from .video import _Video
from .widgets import _Widgets

__all__ = ["ClientStats", "DaitemClient"]


class DaitemClient:
    """Async Daitem Secure client.

    Grouped by resource, one namespace per area of the API::

        async with DaitemClient(email, password) as client:
            systems = await client.account.list_systems()
            status = await client.panel.get_status(systems[0].id, master_code)
    """

    def __init__(
        self,
        email: str,
        password: str,
        *,
        session: aiohttp.ClientSession | None = None,
        api_base: str = API_BASE,
        auth_base: str = AUTH_BASE,
        timeout: float = 20.0,
        token_store: TokenStore | None = None,
        call_timeout: float | None = None,
        max_session_hold: float | None = 120.0,
    ) -> None:
        """`timeout` bounds each request, `call_timeout` each façade call as a whole (off by
        default), `max_session_hold` how long a panel session may stay open before the
        library frees the panel itself (None: never). See the Python guide, "Bound how long
        a call may take".
        """
        self._state = _ClientState(
            email,
            password,
            session=session,
            api_base=api_base,
            auth_base=auth_base,
            timeout=timeout,
            token_store=token_store,
            call_timeout=call_timeout,
            max_session_hold=max_session_hold,
        )
        self._auth = _Auth(self._state)
        self._transport = _Transport(self._state, self._auth)
        self.account = _Account(self._transport)
        self.panel = _Panel(self._state, self._transport)
        self.widgets = _Widgets(self._transport)
        self.commands = _Commands(self._transport, self.account, self.widgets)
        self.logbook = _Logbook(self._transport)
        self.schedule = _Schedule(self._transport)
        self.automation = _Automation(self._transport)
        self.video = _Video(self._transport)
        self.scenarios = _Scenarios(self._transport)
        self.devices = _Devices(self._transport)
        self.notifications = _Notifications(self._transport)
        self.users = _Users(self._transport)

    # -- Lifecycle -------------------------------------------------------------

    async def __aenter__(self) -> Self:
        self._state.ensure_session()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        # A release cut short by a cancelled caller still runs: let it free the panel first.
        await self.panel.wait_released()
        await self._state.close()

    @property
    def stats(self) -> ClientStats:
        """What this client sent so far: requests by endpoint, retries, sessions, refusals."""
        return self._state.stats.copy()

    @property
    def token_url(self) -> str:
        return self._state.token_url

    # -- Authentication ----------------------------------------------------------

    async def login(self) -> None:
        await self._auth.login()

    async def refresh(self) -> None:
        await self._auth.refresh()

    async def logout(self) -> None:
        await self._auth.logout()
