"""Authentication: authorization_code + PKCE, refresh, and resuming a stored session."""

from __future__ import annotations

import contextlib
import json
import logging
import time
from collections.abc import Mapping
from typing import Any

import aiohttp
from yarl import URL

from ..const import ACCESS_TOKEN_TTL, CLIENT_ID, REALM, REDIRECT_URI
from ..exceptions import DaitemAuthError, DaitemConnectionError, Remedy
from .pkce import _login_form_action, _pkce_pair, _query_param
from .state import _ClientState

_LOGGER = logging.getLogger(__name__)

_REDIRECTS = frozenset({301, 302, 303, 307, 308})

#: Remedy of a sign-in that failed on the flow itself, not on the account: the page, the form
#: or the token answer were not what they should be. Asking for the password again would not
#: help, trying later might.
_FLOW = Remedy.RETRY_LATER

#: What a network call can raise short of an answer. aiohttp signals an elapsed `timeout` with
#: the builtin `TimeoutError`, which is not an `aiohttp.ClientError`.
NETWORK_ERRORS = (aiohttp.ClientError, TimeoutError)


def network_reason(exc: BaseException) -> str:
    """The exception's text, or its name when it has none (a timeout usually has none)."""
    return str(exc) or type(exc).__name__


class _Auth:
    def __init__(self, state: _ClientState) -> None:
        self._state = state

    async def login(self) -> None:
        """Authenticate with authorization_code + PKCE by driving the Keycloak form.

        The sign-in runs on a cookie jar of its own, on the same connections. A Keycloak
        single sign-on cookie left in a shared HTTP session would otherwise skip the form
        and sign this client in as whoever owned that cookie, without checking the password.
        """
        state = self._state
        verifier, challenge = _pkce_pair()
        connector = state.ensure_session().connector
        async with aiohttp.ClientSession(
            connector=connector,
            connector_owner=connector is None,
            cookie_jar=aiohttp.CookieJar(unsafe=True),
        ) as session:
            location = await self._sign_in(session, challenge)

        await self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": CLIENT_ID,
                "code": _authorization_code(location),
                "code_verifier": verifier,
                "redirect_uri": REDIRECT_URI,
            }
        )
        _LOGGER.debug("Authenticated (authorization_code + PKCE)")

    async def _sign_in(self, session: aiohttp.ClientSession, challenge: str) -> str | None:
        """Ask for a code, submitting the login form when Keycloak serves one.

        Returns the `Location` of the final redirect, or None when there was none.
        """
        state = self._state
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
                if resp.status in _REDIRECTS:
                    return resp.headers.get("Location")
                if resp.status != 200:
                    raise DaitemAuthError(
                        f"unexpected login page: HTTP {resp.status}", remedy=_FLOW
                    )
                page, page_url = await resp.text(), resp.url
        except NETWORK_ERRORS as exc:
            raise DaitemConnectionError(f"login page unreachable: {network_reason(exc)}") from exc

        action = _login_form_action(page)
        if not action:
            raise DaitemAuthError("login form not found in the Keycloak page", remedy=_FLOW)
        target = self._checked_form_target(page_url, action)
        try:
            async with session.post(
                target,
                data={"username": state.email, "password": state.password, "credentialId": ""},
                allow_redirects=False,
                timeout=state.timeout,
            ) as resp:
                return resp.headers.get("Location") if resp.status in _REDIRECTS else None
        except NETWORK_ERRORS as exc:
            raise DaitemConnectionError(f"login submission failed: {network_reason(exc)}") from exc

    def _checked_form_target(self, page_url: URL, action: str) -> URL:
        """Where to post the password: Keycloak's own login action, nowhere else.

        A gateway page, an error page or a tampered theme could name another host, or
        plain http, in its form.
        """
        target = page_url.join(URL(action))
        base = URL(self._state.auth_base)
        expected = f"{base.path.rstrip('/')}/realms/{REALM}/login-actions/"
        same_origin = (target.scheme, target.host, target.port) == (
            base.scheme,
            base.host,
            base.port,
        )
        if not same_origin or not target.path.startswith(expected):
            raise DaitemAuthError(
                f"the login form posts outside the sign-in server ({target.host}): refused",
                remedy=_FLOW,
            )
        return target

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
        """Revoke the Keycloak session and clear the token store. The panel is unaffected."""
        state = self._state
        if state.refresh_token is None and state.token_store is not None and not state.store_loaded:
            state.store_loaded = True
            state.refresh_token = await state.token_store.load()
        if state.refresh_token:
            await self._revoke(state.refresh_token)
        state.access_token = state.refresh_token = None
        await self._save(None)

    async def _revoke(self, refresh_token: str) -> None:
        state = self._state
        session = state.ensure_session()
        # Best effort: the local tokens are dropped whatever Keycloak answers. Never
        # redirected, since the body carries the refresh token.
        with contextlib.suppress(*NETWORK_ERRORS):
            async with session.post(
                f"{state.auth_base}/realms/{REALM}/protocol/openid-connect/logout",
                data={"client_id": CLIENT_ID, "refresh_token": refresh_token},
                allow_redirects=False,
                timeout=state.timeout,
            ):
                pass

    async def _token_request(self, data: Mapping[str, str]) -> None:
        state = self._state
        session = state.ensure_session()
        try:
            # Never redirected: the body carries the code and its verifier, or the refresh
            # token, and a redirect would send it on as it is.
            async with session.post(
                state.token_url, data=data, allow_redirects=False, timeout=state.timeout
            ) as resp:
                body = await resp.text()
                if resp.status >= 500:
                    # The sign-in server is in trouble: not a reason to replay the login form.
                    raise DaitemConnectionError(f"sign-in server unavailable: HTTP {resp.status}")
                if resp.status != 200:
                    reason = _keycloak_error(body)
                    raise DaitemAuthError(f"token rejected: HTTP {resp.status} {reason}".rstrip())
        except NETWORK_ERRORS as exc:
            raise DaitemConnectionError(
                f"token endpoint call failed: {network_reason(exc)}"
            ) from exc

        try:
            payload = json.loads(body)
        except ValueError as err:
            raise DaitemAuthError(
                "the token endpoint answered something other than JSON", remedy=_FLOW
            ) from err
        if not isinstance(payload, dict) or not isinstance(payload.get("access_token"), str):
            raise DaitemAuthError(
                "the token endpoint answered without an access token", remedy=_FLOW
            )
        await self._store_tokens(payload)

    async def _store_tokens(self, payload: Mapping[str, Any]) -> None:
        """Record a token response, persisting the refresh token when a store is set."""
        state = self._state
        state.access_token = str(payload["access_token"])
        refresh = payload.get("refresh_token")
        if isinstance(refresh, str) and refresh:
            state.refresh_token = refresh
        try:
            expires_in = int(payload.get("expires_in", ACCESS_TOKEN_TTL))
        except (TypeError, ValueError):
            expires_in = ACCESS_TOKEN_TTL
        state.token_expires_at = time.monotonic() + expires_in

        if state.refresh_token:
            await self._save(state.refresh_token)

    async def _save(self, refresh_token: str | None) -> None:
        """Persist the refresh token. A store that fails costs a login later, not this call."""
        store = self._state.token_store
        if store is None:
            return
        try:
            await store.save(refresh_token)
        except Exception as err:
            _LOGGER.warning("Could not persist the refresh token: %s", err)

    def forget(self) -> None:
        """Drop both tokens, so the next request signs in from scratch."""
        state = self._state
        state.access_token = state.refresh_token = None
        state.token_expires_at = 0.0

    async def reject(self, token: str | None) -> None:
        """The API answered 401 with `token`: make the next `ensure_token` renew it.

        Only when it is still the current token, so concurrent requests rejected together
        trigger a single refresh.
        """
        async with self._state.auth_lock:
            if self._state.access_token == token:
                self._state.token_expires_at = 0.0

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
                except DaitemConnectionError:
                    # Not a rejection: let the next call try the stored token again instead
                    # of replaying the login form.
                    state.store_loaded = False
                    state.refresh_token = None
                    raise
                else:
                    _LOGGER.debug("Session resumed from the stored refresh token")
                    return

        await self.login()


def _authorization_code(location: str | None) -> str:
    """The code from Keycloak's redirect to the app, or why there is none."""
    if not location or not location.startswith(REDIRECT_URI):
        raise DaitemAuthError(
            "no authorization code returned: invalid credentials, or an extra "
            "authentication step is required"
        )
    error = _query_param(location, "error")
    if error:
        description = _query_param(location, "error_description") or ""
        raise DaitemAuthError(f"sign-in refused: {error} {description}".rstrip())
    code = _query_param(location, "code")
    if not code:
        raise DaitemAuthError("no authorization code in the redirect", remedy=_FLOW)
    return code


def _keycloak_error(body: str) -> str:
    """The OAuth `error` code of a refusal, without the rest of the server's text."""
    try:
        payload = json.loads(body)
    except ValueError:
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    return error if isinstance(error, str) else ""
