"""HTTP transport: token attachment, the idle-socket retry, and error mapping."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import aiohttp

from ..const import (
    APP_NAME,
    APP_PLATFORM,
    APP_VERSION,
    NO_SESSION_DETAIL,
    USER_AGENT,
    ServerMessage,
)
from ..exceptions import (
    DaitemConnectionError,
    DaitemError,
    DaitemForbiddenError,
    DaitemNoSessionError,
    DaitemSessionBusyError,
)
from .auth import _Auth
from .state import _ClientState

_LOGGER = logging.getLogger(__name__)


def app_headers() -> dict[str, str]:
    """Headers sent on every Topaze call, excluding Authorization."""
    return {
        "X-App-Name": APP_NAME,
        "X-App-Platform": APP_PLATFORM,
        "X-App-Version": APP_VERSION,
        "User-Agent": USER_AGENT,
    }


class _Transport:
    def __init__(self, state: _ClientState, auth: _Auth) -> None:
        self._state = state
        self._auth = auth

    async def request(self, method: str, path: str, *, retry: bool = True, **kwargs: Any) -> Any:
        payload, _ = await self.request_full(method, path, retry=retry, **kwargs)
        return payload

    async def request_full(
        self, method: str, path: str, *, retry: bool = True, **kwargs: Any
    ) -> tuple[Any, Mapping[str, str]]:
        """Perform a request and return both the payload and the response headers."""
        state = self._state
        await self._auth.ensure_token()
        session = state.ensure_session()
        url = f"{state.api_base}{path}"
        headers = app_headers() | {"Authorization": f"Bearer {state.access_token}"}

        # An idle keep-alive socket gets closed server-side, so the next request fails
        # without having been processed, and retrying is safe. But when a request may have
        # been processed and only its response lost, a retry would send the command twice.
        # Callers that drive the alarm therefore pass retry=False.
        attempts = 2 if retry else 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                async with session.request(
                    method, url, headers=headers, timeout=state.timeout, **kwargs
                ) as resp:
                    return await _handle_response(method, path, resp), dict(resp.headers)
            except (aiohttp.ClientConnectionError, aiohttp.ServerDisconnectedError) as exc:
                last_exc = exc
                if attempt + 1 < attempts:
                    _LOGGER.debug("%s %s: connection dropped, retrying once: %s", method, path, exc)
                    await asyncio.sleep(1)
            except aiohttp.ClientError as exc:
                raise DaitemConnectionError(f"{method} {path}: {exc}") from exc
        raise DaitemConnectionError(f"{method} {path}: {last_exc}")


async def _handle_response(method: str, path: str, resp: aiohttp.ClientResponse) -> Any:
    if resp.status < 400:
        if resp.status == 204 or not (await resp.read()):
            return {}
        return await resp.json(content_type=None)

    text = await resp.text()
    message = ""
    details = None
    try:
        data = await resp.json(content_type=None)
        message = data.get("message") or ""
        details = data.get("details")
    except Exception as err:  # deliberately lenient, see the package docstring
        _LOGGER.debug(
            "%s %s: HTTP %s error body is not the expected JSON (content-type %s): %s",
            method,
            path,
            resp.status,
            resp.content_type,
            err,
        )

    if resp.status == 403:
        raise DaitemForbiddenError(f"{method} {path}: access denied for this account")
    if resp.status == 409 or message == ServerMessage.SESSION_ALREADY_OPEN:
        raise DaitemSessionBusyError((details or "").strip() or None)
    no_session = message in (ServerMessage.NO_TTM_SESSION, ServerMessage.INVALID_SESSION)
    # Some endpoints hide a session error behind a generic message, with the real
    # cause only in `details`.
    if not no_session and NO_SESSION_DETAIL in (details or ""):
        no_session = True
    if no_session:
        # Missing or stale session: same remedy, open a fresh one via connect.
        raise DaitemNoSessionError(
            f"{method} {path}: session missing or stale ({message or details})"
        )
    raise DaitemError(f"{method} {path} -> HTTP {resp.status} {text[:200]}")
