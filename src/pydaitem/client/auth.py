"""Authentication: authorization_code + PKCE, refresh, and resuming a stored session."""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Mapping
from typing import Any

import aiohttp

from ..const import ACCESS_TOKEN_TTL, CLIENT_ID, REALM, REDIRECT_URI
from ..exceptions import DaitemAuthError, DaitemConnectionError
from .pkce import _FORM_ACTION_RE, _pkce_pair, _query_param
from .state import _ClientState

_LOGGER = logging.getLogger(__name__)


class _Auth:
    def __init__(self, state: _ClientState) -> None:
        self._state = state

    async def login(self) -> None:
        """Authenticate with authorization_code + PKCE by driving the Keycloak form.

        Keycloak may still hold an SSO session on the underlying `aiohttp.ClientSession`
        (its cookie jar) even though the panel session and mobile app were logged out of
        separately, since those are independent from the browser-level SSO cookie. When
        that happens the authorization endpoint skips the login form and redirects
        straight to `REDIRECT_URI` with a code, exactly like a submitted form does.
        """
        state = self._state
        session = state.ensure_session()
        verifier, challenge = _pkce_pair()

        try:
            async with session.get(
                f"{state.auth_base}/realms/{REALM}/protocol/openid-connect/auth",
                params={
                    "response_type": "code",
                    "client_id": CLIENT_ID,
                    "redirect_uri": REDIRECT_URI,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                    "scope": "openid",
                },
                allow_redirects=False,
                timeout=state.timeout,
            ) as resp:
                if resp.status in (301, 302, 303, 307, 308):
                    location: str | None = resp.headers.get("Location", "")
                    html = None
                elif resp.status == 200:
                    location = None
                    html = await resp.text()
                else:
                    raise DaitemAuthError(f"unexpected login page: HTTP {resp.status}")
        except aiohttp.ClientError as exc:
            raise DaitemConnectionError(f"login page unreachable: {exc}") from exc

        if html is not None:
            match = _FORM_ACTION_RE.search(html)
            if not match:
                raise DaitemAuthError("login form not found in the Keycloak page")
            form_action = match.group(1).replace("&amp;", "&")

            try:
                async with session.post(
                    form_action,
                    data={"username": state.email, "password": state.password, "credentialId": ""},
                    allow_redirects=False,
                    timeout=state.timeout,
                ) as resp:
                    location = resp.headers.get("Location", "")
            except aiohttp.ClientError as exc:
                raise DaitemConnectionError(f"login submission failed: {exc}") from exc

        code = _query_param(location or "", "code")
        if not code:
            raise DaitemAuthError(
                "no authorization code returned: invalid credentials, or an extra "
                "authentication step is required"
            )

        await self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": code,
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
            }
        )
        _LOGGER.debug("Authenticated (authorization_code + PKCE)")

    async def refresh(self) -> None:
        if not self._state.refresh_token:
            raise DaitemAuthError("no refresh token available")
        await self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": self._state.refresh_token,
            }
        )

    async def logout(self) -> None:
        """Revoke the Keycloak session. Does not affect the panel session."""
        state = self._state
        if not state.refresh_token:
            return
        session = state.ensure_session()
        with contextlib.suppress(aiohttp.ClientError):
            await session.post(
                f"{state.auth_base}/realms/{REALM}/protocol/openid-connect/logout",
                data={"client_id": CLIENT_ID, "refresh_token": state.refresh_token},
                timeout=state.timeout,
            )
        state.access_token = state.refresh_token = None
        if state.token_store is not None:
            await state.token_store.save(None)

    async def _token_request(self, data: Mapping[str, str]) -> None:
        state = self._state
        session = state.ensure_session()
        try:
            async with session.post(state.token_url, data=data, timeout=state.timeout) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise DaitemAuthError(f"token rejected: HTTP {resp.status} {body[:200]}")
                payload = await resp.json(content_type=None)
        except aiohttp.ClientError as exc:
            raise DaitemConnectionError(f"token endpoint call failed: {exc}") from exc

        await self._store_tokens(payload)

    async def _store_tokens(self, payload: Mapping[str, Any]) -> None:
        """Record a token response, persisting the refresh token when a store is set."""
        state = self._state
        state.access_token = str(payload["access_token"])
        state.refresh_token = str(payload.get("refresh_token") or state.refresh_token or "") or None
        expires_in = int(payload.get("expires_in", ACCESS_TOKEN_TTL))
        state.token_expires_at = time.monotonic() + expires_in

        if state.token_store is not None and state.refresh_token:
            await state.token_store.save(state.refresh_token)

    async def ensure_token(self) -> None:
        """Authenticate or refresh as needed, with a 60 s margin before expiry."""
        state = self._state
        # Fast path: with a valid token there is nothing to do, so avoid serialising every
        # request through the lock.
        if state.access_token is not None and time.monotonic() < state.token_expires_at - 60:
            return
        async with state.auth_lock:
            # Re-check inside the lock: a concurrent caller may have just refreshed.
            if state.access_token is not None and time.monotonic() < state.token_expires_at - 60:
                return

            if state.access_token is None:
                await self._authenticate()
                return

            try:
                await self.refresh()
            except DaitemAuthError as err:
                _LOGGER.debug("Access token refresh rejected, re-authenticating: %s", err)
                await self._authenticate()

    async def _authenticate(self) -> None:
        """Resume from a stored refresh token when possible, else log in for real.

        A stored token can be rejected at any time, since Keycloak also caps the overall
        SSO session, so this must degrade quietly to a full login rather than raise.
        """
        state = self._state
        if state.token_store is not None and not state.store_loaded:
            state.store_loaded = True
            stored = await state.token_store.load()
            if stored:
                state.refresh_token = stored
                try:
                    await self.refresh()
                except DaitemAuthError as err:
                    _LOGGER.debug("Stored refresh token rejected, logging in: %s", err)
                    state.refresh_token = None
                else:
                    _LOGGER.debug("Session resumed from the stored refresh token")
                    return

        await self.login()
