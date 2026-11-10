"""HTTP transport: token attachment, the app's retry rules, and error mapping."""

from __future__ import annotations

import asyncio
import logging
import random
import re
import time
from collections.abc import Mapping
from typing import Any

import aiohttp

from ..const import (
    APP_NAME,
    APP_PLATFORM,
    APP_VERSION,
    NO_SESSION_DETAIL,
    RETRY_DELAY,
    RETRY_LIMIT,
    USER_AGENT,
    ServerMessage,
)
from ..exceptions import (
    DaitemApiError,
    DaitemAuthError,
    DaitemBadCodeError,
    DaitemConnectionError,
    DaitemForbiddenError,
    DaitemNoSessionError,
    DaitemRateLimitedError,
    DaitemSessionBusyError,
    DaitemSessionRestrictedError,
    DaitemTransmitterOfflineError,
    Remedy,
)
from . import trace
from .auth import _Auth, network_reason
from .pressure import endpoint
from .state import _ClientState

_LOGGER = logging.getLogger(__name__)

KEEP_ALIVE_PATH = "/topaze/authenticate/keepAlive"

#: The panel connect itself, not the poll of a deferred one (`connect/{transactionId}`).
_CONNECT_PATH_RE = re.compile(r"/topaze/v5/systems/\d+/connect")


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

    async def request_object(
        self, method: str, path: str, *, retry: bool = True, **kwargs: Any
    ) -> dict[str, Any]:
        """Perform a request whose answer is a JSON object (an empty body reads as `{}`).

        Raises `DaitemApiError` when the answer is something else, rather than handing the
        caller a value of the wrong type.
        """
        payload = await self.request(method, path, retry=retry, **kwargs)
        if not isinstance(payload, dict):
            raise DaitemApiError(
                f"{method} {path}: expected a JSON object, got {type(payload).__name__}"
            )
        return payload

    async def request_bytes(
        self, method: str, path: str, *, retry: bool = True, **kwargs: Any
    ) -> bytes:
        """Perform a request whose answer is a file (a video clip), not JSON."""
        payload, _ = await self.request_full(method, path, retry=retry, binary=True, **kwargs)
        data: bytes = payload
        return data

    async def request_full(
        self,
        method: str,
        path: str,
        *,
        retry: bool = True,
        binary: bool = False,
        guarded: bool = True,
        **kwargs: Any,
    ) -> tuple[Any, Mapping[str, str]]:
        """Perform a request and return both the payload and the response headers.

        Follows the app's retry rules: a 401 renews the access token and replays the
        request once, which is safe since a rejected token means nothing ran. A dropped
        connection or a timeout is retried `RETRY_LIMIT` times, `RETRY_DELAY` apart, only
        when `retry` is true: the request may have been processed and only its response
        lost, so a replay could send a command twice. Callers that write therefore pass
        `retry=False`. A timeout is not sent again: a server that did not answer in time is
        not helped by the same request half a second later.

        While the API asks to back off (see `pressure._Breaker`) the request is refused
        without the network. `guarded=False` sends it anyway: the panel release does, since
        a session left open would lock the mobile app out.
        """
        state = self._state
        if guarded and (wait := state.breaker.remaining()):
            state.stats.refused_locally += 1
            raise DaitemRateLimitedError(
                f"{method} {path}: not sent, the API asked to back off for {wait:.0f} s more"
            )
        url = f"{state.api_base}{path}"
        retries = 0
        renewed = False
        while True:
            await self._auth.ensure_token()
            session = state.ensure_session()
            token = state.access_token
            started = time.monotonic()
            state.stats.requests[endpoint(method, path)] += 1
            headers = app_headers() | {"Authorization": f"Bearer {token}"}
            try:
                # Only a read may follow a redirect: a write carries the alarm code or other
                # data that a redirect would send on, as it is, to wherever it points.
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    timeout=state.timeout,
                    allow_redirects=method == "GET",
                    **kwargs,
                ) as resp:
                    # One line per request, without its body or headers: they carry the code,
                    # the tokens and personal data.
                    _LOGGER.debug(
                        "%s %s -> HTTP %s in %s ms%s",
                        method,
                        path,
                        resp.status,
                        trace.elapsed_ms(started),
                        trace.suffix(),
                    )
                    _log_cache_headers(state, method, path, resp.headers)
                    if resp.status == 401 and not renewed:
                        _LOGGER.debug("%s %s: token rejected, renewing it", method, path)
                        renewed = True
                        await self._auth.reject(token)
                        continue
                    if resp.status == 401:
                        # A token just renewed is rejected too: sign in from scratch next time.
                        self._auth.forget()
                    try:
                        payload = await _handle_response(method, path, resp, binary=binary)
                    except DaitemApiError as err:
                        state.breaker.failed(err)
                        raise
                    state.breaker.succeeded()
                    # A copy keeps aiohttp's case-insensitive lookup: `Location` may come in
                    # any case.
                    return payload, resp.headers.copy()
            except (aiohttp.ClientConnectionError, TimeoutError) as exc:
                # A timeout is a lost answer like a dropped connection: the request may have
                # been processed, so it is replayed only when that is safe.
                if not retry or retries >= RETRY_LIMIT or isinstance(exc, TimeoutError):
                    _LOGGER.debug(
                        "%s %s -> no answer after %s ms, giving up: %s%s",
                        method,
                        path,
                        trace.elapsed_ms(started),
                        network_reason(exc),
                        trace.suffix(),
                    )
                    raise DaitemConnectionError(
                        f"{method} {path}: {network_reason(exc)}",
                        remedy=_lost_answer_remedy(exc, retry=retry),
                    ) from exc
                retries += 1
                state.stats.retries += 1
                _LOGGER.debug(
                    "%s %s: connection dropped, retry %s: %s%s",
                    method,
                    path,
                    retries,
                    network_reason(exc),
                    trace.suffix(),
                )
                # The app's delay on average, spread so clients that failed together do not
                # come back together.
                await asyncio.sleep(RETRY_DELAY * random.uniform(0.5, 1.5))
            except aiohttp.ClientError as exc:
                raise DaitemConnectionError(
                    f"{method} {path}: {exc}", remedy=_lost_answer_remedy(exc, retry=retry)
                ) from exc


#: Headers that would let a client ask "has it changed?" instead of reading it all again.
_CACHE_HEADERS = ("ETag", "Last-Modified", "Cache-Control")


def _log_cache_headers(
    state: _ClientState, method: str, path: str, headers: Mapping[str, str]
) -> None:
    """Log, once per endpoint, any header a conditional request could build on.

    No capture shows the API sending one. If it does, `If-None-Match` would let a poll
    cost a 304 rather than a full answer: this line is how to find out.
    """
    found = {name: headers[name] for name in _CACHE_HEADERS if name in headers}
    key = endpoint(method, path)
    if found and key not in state.cache_headers_seen:
        state.cache_headers_seen.add(key)
        _LOGGER.debug("%s: cache headers %s", key, found)


def _lost_answer_remedy(exc: BaseException, *, retry: bool) -> Remedy | None:
    """`CHECK_STATE` for a write that was sent and lost its answer, None otherwise.

    Only writes pass `retry=False`. A connection that never opened sent nothing, so trying
    again later is safe. Past that point the panel may have obeyed.
    """
    if retry or isinstance(exc, aiohttp.ClientConnectorError):
        return None
    return Remedy.CHECK_STATE


async def _handle_response(
    method: str, path: str, resp: aiohttp.ClientResponse, *, binary: bool = False
) -> Any:
    if 300 <= resp.status < 400:
        raise DaitemApiError(
            f"{method} {path}: HTTP {resp.status} redirect, not followed", status=resp.status
        )
    if resp.status < 400:
        if binary:
            return await resp.read()
        if resp.status == 204 or not (await resp.read()):
            return {}
        try:
            return await resp.json(content_type=None)
        except ValueError as err:
            # A gateway page or a truncated body: still the API's answer, not a bug here.
            raise DaitemApiError(
                f"{method} {path}: HTTP {resp.status} answer is not JSON", status=resp.status
            ) from err

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

    if resp.status == 401:
        # Reached only once a renewed token was rejected too.
        raise DaitemAuthError(f"{method} {path}: access token rejected (HTTP 401)")
    raise api_error(method, path, resp.status, message, details, text)


def api_error(
    method: str,
    path: str,
    status: int,
    message: Any,
    details: Any = None,
    text: str = "",
) -> DaitemApiError:
    """The exception for an error the API reported, typed by its message first.

    The app decodes the message first and only then looks at the status (see
    docs/api/reference.md). Also used for
    the `error` of an asynchronous answer, which arrives with a 200.
    """
    # The body is the server's: a message that is not a string must not reach the dict
    # lookup below, where an unhashable one would raise a TypeError outside DaitemError.
    message = message if isinstance(message, str) else (str(message) if message else "")
    detail_text = details if isinstance(details, str) else None
    info: dict[str, Any] = {
        "status": status,
        "server_message": message or None,
        "details": detail_text,
    }
    holder = (detail_text or "").strip() or None
    if message == ServerMessage.SESSION_ALREADY_OPEN or (status == 409 and not message):
        return DaitemSessionBusyError(holder, **info)
    if status == 403 and path == KEEP_ALIVE_PATH:
        # The app treats it as the session being lost, not as a missing right.
        return DaitemNoSessionError(f"{method} {path}: panel session lost (HTTP 403)", **info)
    typed = _TYPED_MESSAGES.get(message)
    if typed is not None:
        return typed(f"{method} {path}: {message}{_detail(detail_text)}", **info)
    # Some endpoints hide a session error behind a generic message, with the real cause
    # only in `details`.
    if NO_SESSION_DETAIL in (detail_text or ""):
        return DaitemNoSessionError(
            f"{method} {path}: session missing or stale ({message or detail_text})", **info
        )
    if status == 403:
        # A bare 403 on connect is not an owner-only resource: connect is open to every
        # account, with its own code. The Home Assistant integration has read it as a wrong
        # code since its first release, but no capture records it. Asking for the code again
        # is right either way, where `NOT_PERMITTED` would leave the user stuck.
        remedy = Remedy.ASK_CODE if _CONNECT_PATH_RE.fullmatch(path) else None
        return DaitemForbiddenError(
            f"{method} {path}: access denied for this account", remedy=remedy, **info
        )
    if status == 409:
        return DaitemSessionBusyError(holder, **info)
    return DaitemApiError(
        f"{method} {path} -> HTTP {status} {message}".rstrip(), body=text[:200] or None, **info
    )


def _detail(details: str | None) -> str:
    return f" ({details.strip()})" if details and details.strip() else ""


#: Server messages a consumer should react to, and the exception each one raises. Missing and
#: stale sessions share a remedy (open a fresh one via connect), hence one exception.
_TYPED_MESSAGES: dict[str, type[DaitemApiError]] = {
    ServerMessage.NO_TTM_SESSION: DaitemNoSessionError,
    ServerMessage.INVALID_SESSION: DaitemNoSessionError,
    ServerMessage.BAD_PIN_CODE: DaitemBadCodeError,
    ServerMessage.TT_DISCONNECTED: DaitemTransmitterOfflineError,
    ServerMessage.CONNECTION_ERROR: DaitemTransmitterOfflineError,
    ServerMessage.OVER_LIMIT: DaitemRateLimitedError,
    ServerMessage.POOL_FULL: DaitemRateLimitedError,
    ServerMessage.ACCESS_FORBIDDEN: DaitemForbiddenError,
    ServerMessage.SESSION_RESTRICTED: DaitemSessionRestrictedError,
}
