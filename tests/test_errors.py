"""Error-typing tests against a real local aiohttp server.

Responses are served from a test server rather than mocked, so the real network stack is
exercised and no fragile mock dependency is needed (aioresponses 0.7.9 is incompatible
with aiohttp 3.14).

Every condition below was observed on the live API. Mapping them to distinct exceptions
drives consumer behaviour: Home Assistant reacts differently to a busy session, a missing
one, or a denied access.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator, Callable

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import (
    DaitemClient,
    DaitemError,
    DaitemForbiddenError,
    DaitemNoSessionError,
    DaitemSessionBusyError,
)

SYSTEM_ID = 123456
STATE_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/state"
CONNECT_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/connect"
DISCONNECT_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/disconnect"
LOGBOOK_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/logbook"


def json_error(status: int, message: str, details: str | None = None) -> Callable:
    async def handler(_request: web.Request) -> web.Response:
        return web.json_response({"message": message, "details": details}, status=status)

    return handler


async def serve(routes: list[tuple[str, str, Callable]]) -> AsyncIterator[DaitemClient]:
    """Start a local server and return a pre-authenticated client pointing at it."""
    app = web.Application()
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()

    client = DaitemClient(
        "account@example.test", "password", api_base=str(server.make_url("")).rstrip("/")
    )
    # Short-circuit the Keycloak flow: these tests cover error handling only.
    client._state.access_token = "test-token"
    client._state.refresh_token = "test-refresh"
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        yield client
    finally:
        await client.close()
        await server.close()


async def test_no_session_raises_no_session_error() -> None:
    """500 status.nottmsessionid: no session open on the panel."""
    routes = [
        (
            "GET",
            STATE_PATH,
            json_error(500, "status.nottmsessionid", "Failed to get last TTM session"),
        )
    ]
    async for client in serve(routes):
        with pytest.raises(DaitemNoSessionError):
            await client.panel.get_state(SYSTEM_ID)


async def test_invalid_session_raises_no_session_error() -> None:
    """500 transmitter.error.invalidsessionid: stale session.

    Regression: found during live smoke testing, this was treated as a generic error and
    stopped the opportunistic read from falling back to connect.
    """
    routes = [
        (
            "GET",
            STATE_PATH,
            json_error(500, "transmitter.error.invalidsessionid", "Invalid session id: abc"),
        )
    ]
    async for client in serve(routes):
        with pytest.raises(DaitemNoSessionError):
            await client.panel.get_state(SYSTEM_ID)


async def test_session_already_open_raises_busy_error() -> None:
    """409: another device holds the panel session."""
    routes = [
        (
            "POST",
            CONNECT_PATH,
            json_error(409, "transmitter.connection.sessionalreadyopen", "owner "),
        )
    ]
    async for client in serve(routes):
        with pytest.raises(DaitemSessionBusyError) as excinfo:
            await client.panel.connect(SYSTEM_ID, "0000")
        assert excinfo.value.holder == "owner"


async def test_forbidden_raises_forbidden_error() -> None:
    """403: owner-only resource, such as the logbook."""
    routes = [("POST", LOGBOOK_PATH, json_error(403, "Access is denied"))]
    async for client in serve(routes):
        with pytest.raises(DaitemForbiddenError):
            await client._transport.request("POST", LOGBOOK_PATH)


async def test_unknown_error_stays_generic() -> None:
    async def bad_gateway(_request: web.Request) -> web.Response:
        return web.Response(status=502, text="Bad Gateway")

    async for client in serve([("GET", STATE_PATH, bad_gateway)]):
        with pytest.raises(DaitemError):
            await client.panel.get_state(SYSTEM_ID)


async def test_failed_disconnect_is_logged_not_raised(caplog: pytest.LogCaptureFixture) -> None:
    """`central_session` must always release the block even if releasing the panel fails.

    A leaked session is what a later DaitemSessionBusyError looks like, so the failure is
    traced at debug instead of vanishing silently.
    """

    async def connect(_request: web.Request) -> web.Response:
        return web.json_response({"ttmSessionId": "sess", "systemState": "off", "groups": []})

    routes = [
        ("POST", CONNECT_PATH, connect),
        ("POST", DISCONNECT_PATH, json_error(500, "unexpected.error")),
    ]
    async for client in serve(routes):
        with caplog.at_level(logging.DEBUG, logger="pydaitem.client"):
            async with client.panel.session(SYSTEM_ID, "0000"):
                pass  # The block itself must not raise.

        assert "Could not release the panel session" in caplog.text


async def test_non_json_error_body_is_logged_without_leaking_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A non-JSON error body (e.g. a proxy's HTML page) must not crash parsing.

    The body itself must not reach the log: only the status and content type do.
    """

    async def bad_gateway(_request: web.Request) -> web.Response:
        return web.Response(status=502, text="<html>this-should-not-be-logged</html>")

    async for client in serve([("GET", STATE_PATH, bad_gateway)]):
        with caplog.at_level(logging.DEBUG, logger="pydaitem.client"), pytest.raises(DaitemError):
            await client.panel.get_state(SYSTEM_ID)

        assert "is not the expected JSON" in caplog.text
        assert "this-should-not-be-logged" not in caplog.text


async def test_get_status_falls_back_to_connect() -> None:
    """The opportunistic read opens a session when none is usable."""
    calls: list[str] = []

    async def state(_request: web.Request) -> web.Response:
        calls.append("state")
        if len(calls) == 1:
            return web.json_response(
                {"message": "transmitter.error.invalidsessionid", "details": "Invalid session id"},
                status=500,
            )
        return web.json_response({"systemState": "on", "groups": [{"id": 1, "active": True}]})

    async def connect(_request: web.Request) -> web.Response:
        calls.append("connect")
        return web.json_response({"ttmSessionId": "sess", "systemState": "off", "groups": []})

    async def disconnect(_request: web.Request) -> web.Response:
        calls.append("disconnect")
        return web.json_response({"status": "OK"})

    routes = [
        ("GET", STATE_PATH, state),
        ("POST", CONNECT_PATH, connect),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for client in serve(routes):
        status = await client.panel.get_status(SYSTEM_ID, "0000")

        assert status.state == "on"
        assert status.active_groups == [1]
        # Proves the strategy: read, fall back to connect, re-read, release.
        assert calls == ["state", "connect", "state", "disconnect"]
        assert client.panel.ttm_session_id is None
