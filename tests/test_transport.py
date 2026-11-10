"""The transport's retry rules, against a real local server.

They follow the app's retry rules (docs/api/reference.md#retries): a rejected token is
renewed once, a dropped connection is retried twice on requests that are safe to replay, and
commands are never replayed after a dropped connection.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import (
    DaitemApiError,
    DaitemAuthError,
    DaitemClient,
    DaitemConnectionError,
    Remedy,
)
from pydaitem.const import REALM, RETRY_LIMIT

SYSTEM_ID = 123456
STATE_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/state"
COMMAND_PATH = f"/topaze/v1/action/systems/{SYSTEM_ID}/sendSystemCommand"
TOKEN_PATH = f"/realms/{REALM}/protocol/openid-connect/token"


async def serve(routes: list[tuple[str, str, Callable]]) -> AsyncIterator[DaitemClient]:
    """A pre-authenticated client whose API and Keycloak are both the local server."""
    app = web.Application()
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()
    base = str(server.make_url("")).rstrip("/")
    client = DaitemClient("account@example.test", "password", api_base=base, auth_base=base)
    client._state.access_token = "old-token"
    client._state.refresh_token = "refresh"
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        yield client
    finally:
        await client.close()
        await server.close()


def renewed_token(calls: list[str]) -> Callable:
    async def token(_request: web.Request) -> web.Response:
        calls.append("token")
        return web.json_response({"access_token": "new-token", "expires_in": 1800})

    return token


def dropping(calls: list[str]) -> Callable:
    """A handler that closes the connection without answering."""

    async def handler(request: web.Request) -> web.Response:
        calls.append("request")
        assert request.transport is not None
        request.transport.close()
        return web.Response()

    return handler


async def test_rejected_token_is_renewed_and_the_request_replayed() -> None:
    calls: list[str] = []

    async def state(request: web.Request) -> web.Response:
        calls.append(request.headers["Authorization"])
        if request.headers["Authorization"] == "Bearer old-token":
            return web.Response(status=401)
        return web.json_response({"systemState": "off"})

    routes = [("GET", STATE_PATH, state), ("POST", TOKEN_PATH, renewed_token(calls))]
    async for client in serve(routes):
        status = await client.panel.get_state(SYSTEM_ID)
        assert status.state == "off"
        assert calls == ["Bearer old-token", "token", "Bearer new-token"]


async def test_command_is_replayed_after_a_rejected_token() -> None:
    """A 401 means nothing ran, so even a command is safe to send again."""
    calls: list[str] = []

    async def command(request: web.Request) -> web.Response:
        calls.append("command")
        if request.headers["Authorization"] == "Bearer old-token":
            return web.Response(status=401)
        return web.json_response({"systemState": "tempo", "commandStatus": "CMD_OK"})

    routes = [("POST", COMMAND_PATH, command), ("POST", TOKEN_PATH, renewed_token(calls))]
    async for client in serve(routes):
        await client.commands.arm(SYSTEM_ID)
        assert calls == ["command", "token", "command"]


async def test_token_rejected_twice_is_an_auth_error() -> None:
    calls: list[str] = []

    async def state(_request: web.Request) -> web.Response:
        calls.append("state")
        return web.Response(status=401)

    routes = [("GET", STATE_PATH, state), ("POST", TOKEN_PATH, renewed_token(calls))]
    async for client in serve(routes):
        with pytest.raises(DaitemAuthError):
            await client.panel.get_state(SYSTEM_ID)
        assert calls == ["state", "token", "state"]


async def test_dropped_connection_is_retried_twice_then_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Counted from the log: aiohttp may itself replay an idempotent request once on a
    dropped connection, so the server sees more requests than pydaitem sends."""
    calls: list[str] = []
    async for client in serve([("GET", STATE_PATH, dropping(calls))]):
        with (
            caplog.at_level(logging.DEBUG, logger="pydaitem.client"),
            pytest.raises(DaitemConnectionError) as raised,
        ):
            await client.panel.get_state(SYSTEM_ID)
        retries = [r for r in caplog.records if "connection dropped, retry" in r.getMessage()]
        assert len(retries) == RETRY_LIMIT
        assert raised.value.remedy is Remedy.RETRY_LATER


async def test_dropped_connection_then_success() -> None:
    calls: list[str] = []
    drop = dropping(calls)

    async def state(request: web.Request) -> web.Response:
        if not calls:
            return await drop(request)
        calls.append("request")
        return web.json_response({"systemState": "on"})

    async for client in serve([("GET", STATE_PATH, state)]):
        status = await client.panel.get_state(SYSTEM_ID)
        assert status.state == "on"
        assert calls[-1] == "request"


async def test_command_is_never_replayed_after_a_dropped_connection() -> None:
    """The panel may have obeyed and only the answer been lost: a replay could arm twice."""
    calls: list[str] = []
    async for client in serve([("POST", COMMAND_PATH, dropping(calls))]):
        with pytest.raises(DaitemConnectionError) as raised:
            await client.commands.arm(SYSTEM_ID)
        assert calls == ["request"]
        assert raised.value.remedy is Remedy.CHECK_STATE


async def test_a_write_whose_connection_never_opened_can_be_sent_again_later() -> None:
    """Nothing reached the panel, so the caller has no state to check first."""
    client = DaitemClient("account@example.test", "password", api_base="http://127.0.0.1:1")
    client._state.access_token = "token"
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        with pytest.raises(DaitemConnectionError) as raised:
            await client.commands.arm(SYSTEM_ID)
        assert raised.value.remedy is Remedy.RETRY_LATER
    finally:
        await client.close()


async def test_timeout_is_a_connection_error_and_is_not_sent_again(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """aiohttp signals an elapsed timeout with the builtin TimeoutError, not a ClientError.

    Unlike the app, the library does not send it again: a server that did not answer in time
    is not helped by the same request half a second later, it only gets more of them.
    """
    calls: list[str] = []

    async def slow(_request: web.Request) -> web.Response:
        calls.append("request")
        await asyncio.sleep(1)
        return web.json_response({"systemState": "off"})

    async for client in serve([("GET", STATE_PATH, slow)]):
        client._state.timeout = aiohttp.ClientTimeout(total=0.05)
        with (
            caplog.at_level(logging.DEBUG, logger="pydaitem.client"),
            pytest.raises(DaitemConnectionError, match="TimeoutError") as raised,
        ):
            await client.panel.get_state(SYSTEM_ID)
        assert raised.value.remedy is Remedy.RETRY_LATER
        assert not [r for r in caplog.records if "connection dropped, retry" in r.getMessage()]
        assert calls == ["request"]


async def test_command_is_never_replayed_after_a_timeout() -> None:
    calls: list[str] = []

    async def slow(_request: web.Request) -> web.Response:
        calls.append("request")
        await asyncio.sleep(1)
        return web.json_response({})

    async for client in serve([("POST", COMMAND_PATH, slow)]):
        client._state.timeout = aiohttp.ClientTimeout(total=0.05)
        with pytest.raises(DaitemConnectionError) as raised:
            await client.commands.arm(SYSTEM_ID)
        assert calls == ["request"]
        assert raised.value.remedy is Remedy.CHECK_STATE


@pytest.mark.parametrize(
    ("method", "path", "call"),
    [
        (
            "PUT",
            f"/topaze/v5/systems/{SYSTEM_ID}/schedule/7",
            lambda c: c.schedule.update_program(SYSTEM_ID, {"id": 7}),
        ),
        (
            "DELETE",
            f"/topaze/v5/systems/{SYSTEM_ID}/schedule/7",
            lambda c: c.schedule.delete_program(SYSTEM_ID, 7),
        ),
        (
            "PUT",
            f"/topaze/v5/systems/{SYSTEM_ID}/schedule/activate",
            lambda c: c.schedule.set_active(SYSTEM_ID, True),
        ),
    ],
)
async def test_schedule_writes_are_never_replayed(
    method: str, path: str, call: Callable, caplog: pytest.LogCaptureFixture
) -> None:
    """They change when the alarm arms itself, so they follow the commands' rule."""
    calls: list[str] = []
    async for client in serve([(method, path, dropping(calls))]):
        with (
            caplog.at_level(logging.DEBUG, logger="pydaitem.client"),
            pytest.raises(DaitemConnectionError) as raised,
        ):
            await call(client)
        assert not [r for r in caplog.records if "retry" in r.getMessage()]
        assert raised.value.remedy is Remedy.CHECK_STATE


async def test_logout_releases_its_answer_and_survives_a_timeout() -> None:
    async def slow(_request: web.Request) -> web.Response:
        await asyncio.sleep(1)
        return web.Response()

    logout = f"/realms/{REALM}/protocol/openid-connect/logout"
    async for client in serve([("POST", logout, slow)]):
        client._state.timeout = aiohttp.ClientTimeout(total=0.05)
        await client.logout()
        assert client._state.access_token is None and client._state.refresh_token is None


async def test_connect_is_never_replayed_after_a_timeout() -> None:
    """The panel may have opened the session: a replay would find it busy."""
    calls: list[str] = []

    async def slow(_request: web.Request) -> web.Response:
        calls.append("connect")
        await asyncio.sleep(1)
        return web.json_response({})

    path = f"/topaze/v5/systems/{SYSTEM_ID}/connect"
    async for client in serve([("POST", path, slow)]):
        client._state.timeout = aiohttp.ClientTimeout(total=0.05)
        with pytest.raises(DaitemConnectionError) as raised:
            await client.panel.connect(SYSTEM_ID, "0000")
        assert calls == ["connect"]
        # The session was released on the way out: opening one later is safe.
        assert raised.value.remedy is Remedy.RETRY_LATER


async def test_a_success_that_is_not_json_is_an_api_error() -> None:
    """A gateway page answered with a 200 stays inside the DaitemError hierarchy."""

    async def html(_request: web.Request) -> web.Response:
        return web.Response(text="<html>maintenance</html>", content_type="text/html")

    async for client in serve([("GET", STATE_PATH, html)]):
        with pytest.raises(DaitemApiError, match="not JSON") as raised:
            await client.panel.get_state(SYSTEM_ID)
        assert raised.value.status == 200


async def test_an_error_whose_message_is_not_a_string_is_an_api_error() -> None:
    """An unhashable `message` must not escape as a TypeError from the typed lookup."""

    async def odd(_request: web.Request) -> web.Response:
        return web.json_response({"message": {"code": 7}}, status=500)

    async for client in serve([("GET", STATE_PATH, odd)]):
        with pytest.raises(DaitemApiError) as raised:
            await client.panel.get_state(SYSTEM_ID)
        assert raised.value.status == 500
