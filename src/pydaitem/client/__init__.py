"""Async client for the private Daitem Secure API.

Depends only on `aiohttp`.

Design notes from the reverse engineering:

- Authentication uses OAuth2 **authorization_code + PKCE**. The Keycloak realm refuses the
  `password` grant, so it is not implemented.
- The panel accepts **a single session at a time**, across all accounts; a concurrent
  `connect` returns 409. Hence `panel.session()`, which releases as soon as possible, and
  `panel.get_status()`, which reads without opening a session when it can.
- Reading the state requires a session to exist, held by any device.

WARNING: `commands.arm()`, `commands.arm_groups()`, `commands.disarm()` and the
`schedule.*` methods drive a real alarm, directly or by changing when it arms and disarms
itself.
"""

from __future__ import annotations

from typing import Self

import aiohttp

from ..const import API_BASE, AUTH_BASE, SystemState
from ..tokens import TokenStore
from .account import _Account
from .auth import _Auth
from .commands import _Commands
from .logbook import _Logbook
from .panel import _Panel
from .schedule import _Schedule
from .state import _ClientState
from .transport import _Transport

__all__ = ["DaitemClient", "SystemState"]


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
    ) -> None:
        self._state = _ClientState(
            email,
            password,
            session=session,
            api_base=api_base,
            auth_base=auth_base,
            timeout=timeout,
            token_store=token_store,
        )
        self._auth = _Auth(self._state)
        self._transport = _Transport(self._state, self._auth)
        self.account = _Account(self._transport)
        self.panel = _Panel(self._state, self._transport)
        self.commands = _Commands(self._transport, self.account)
        self.logbook = _Logbook(self._transport)
        self.schedule = _Schedule(self._transport)

    # -- Lifecycle -------------------------------------------------------------

    async def __aenter__(self) -> Self:
        self._state.ensure_session()
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()

    async def close(self) -> None:
        await self._state.close()

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
