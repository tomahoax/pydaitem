"""Shared, mutable state: config, tokens, and the underlying `aiohttp` session.

Every service (`_Auth`, `_Transport`, `_Panel`, ...) is handed this same instance, so a token
refreshed by `_Auth` is immediately visible to `_Transport`, and a panel session opened by
`_Panel` is visible everywhere without any service reaching into another.
"""

from __future__ import annotations

import asyncio

import aiohttp

from ..const import REALM
from ..tokens import TokenStore


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
    ) -> None:
        self.email = email
        self.password = password
        self.api_base = api_base.rstrip("/")
        self.auth_base = auth_base.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = session
        self.owns_session = session is None
        self.access_token: str | None = None
        self.refresh_token: str | None = None
        self.token_expires_at: float = 0.0
        self.auth_lock = asyncio.Lock()
        self.token_store = token_store
        self.store_loaded = False
        self.ttm_session_id: str | None = None

    async def close(self) -> None:
        if self.owns_session and self.session is not None:
            await self.session.close()
            self.session = None

    def ensure_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession()
            self.owns_session = True
        return self.session

    @property
    def token_url(self) -> str:
        return f"{self.auth_base}/realms/{REALM}/protocol/openid-connect/token"
