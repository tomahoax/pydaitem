"""A deferred `connect`, polled until the panel answers, against a real local server.

The shape follows the logbook job.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import (
    DaitemApiError,
    DaitemBadCodeError,
    DaitemClient,
    DaitemConnectionError,
)
from pydaitem.client import panel

SYSTEM_ID = 123456
CONNECT_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/connect"
POLL_PATH = f"{CONNECT_PATH}/tx-1"
DISCONNECT_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/disconnect"


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(panel, "CONNECT_POLL_INTERVAL", 0.0)


async def serve(routes: list[tuple[str, str, Callable]]) -> AsyncIterator[DaitemClient]:
    app = web.Application()
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()
    client = DaitemClient(
        "account@example.test", "password", api_base=str(server.make_url("")).rstrip("/")
    )
    client._state.access_token = "test-token"
    client._state.refresh_token = "test-refresh"
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        yield client
    finally:
        await client.close()
        await server.close()


def deferred(location: str = "/v5/systems/123456/connect/tx-1") -> Callable:
    """`connect` answering 202 with the poll path in `Location`, without the /topaze prefix."""

    async def handler(_request: web.Request) -> web.Response:
        return web.json_response(
            {"message": "ACCEPTED"}, status=202, headers={"Location": location}
        )

    return handler


def polls(*answers: dict[str, object]) -> Callable:
    remaining = list(answers)

    async def handler(_request: web.Request) -> web.Response:
        return web.json_response(remaining.pop(0) if len(remaining) > 1 else remaining[0])

    return handler


DONE = {"ttmSessionId": "sess", "systemState": "off", "groups": []}


@pytest.mark.parametrize(
    ("pending", "done"),
    [("PENDING", "DONE"), ("request_status_pending", "request_status_done")],
)
async def test_deferred_connect_is_polled_until_done(pending: str, done: str) -> None:
    routes = [
        ("POST", CONNECT_PATH, deferred()),
        (
            "GET",
            POLL_PATH,
            polls(
                {"status": pending, "response": None, "error": None},
                {"status": pending, "response": None, "error": None},
                {"status": done, "response": DONE, "error": None},
            ),
        ),
    ]
    async for client in serve(routes):
        status = await client.panel.connect(SYSTEM_ID, "0000")
        assert status.state == "off"
        assert client.panel.ttm_session_id == "sess"


async def test_deferred_connect_error_is_typed_like_an_immediate_one() -> None:
    error = {"message": "transmitter.connection.badpincode", "details": "wrong code"}
    routes = [
        ("POST", CONNECT_PATH, deferred()),
        ("GET", POLL_PATH, polls({"status": "ERROR", "response": None, "error": error})),
    ]
    async for client in serve(routes):
        with pytest.raises(DaitemBadCodeError):
            await client.panel.connect(SYSTEM_ID, "0000")
        assert client.panel.ttm_session_id is None


async def test_deferred_connect_that_never_ends_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(panel, "CONNECT_POLL_TIMEOUT", 0.0)
    released: list[bool] = []

    async def disconnect(_request: web.Request) -> web.Response:
        released.append(True)
        return web.json_response({"status": "OK"})

    routes = [
        ("POST", CONNECT_PATH, deferred()),
        ("GET", POLL_PATH, polls({"status": "PENDING", "response": None})),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for client in serve(routes):
        with pytest.raises(DaitemConnectionError):
            await client.panel.connect(SYSTEM_ID, "0000")
        assert released == [True]


async def test_poll_path_outside_connect_is_refused() -> None:
    """A `Location` header must not send the authenticated request elsewhere."""
    routes = [("POST", CONNECT_PATH, deferred("/v1/user"))]
    async for client in serve(routes):
        with pytest.raises(DaitemApiError, match="not a connect poll path"):
            await client.panel.connect(SYSTEM_ID, "0000")


async def test_immediate_connect_is_unchanged() -> None:
    async def connect(_request: web.Request) -> web.Response:
        return web.json_response(DONE)

    async for client in serve([("POST", CONNECT_PATH, connect)]):
        await client.panel.connect(SYSTEM_ID, "0000")
        assert client.panel.ttm_session_id == "sess"


async def test_deferred_connect_whose_poll_answer_is_lost_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The panel may still open the session: it must not stay behind, blocking the app."""
    monkeypatch.setattr("pydaitem.client.transport.RETRY_DELAY", 0.0)
    released: list[bool] = []

    async def dropped(request: web.Request) -> web.Response:
        assert request.transport is not None
        request.transport.close()
        return web.Response()

    async def disconnect(_request: web.Request) -> web.Response:
        released.append(True)
        return web.json_response({"status": "OK"})

    routes = [
        ("POST", CONNECT_PATH, deferred()),
        ("GET", POLL_PATH, dropped),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for client in serve(routes):
        with pytest.raises(DaitemConnectionError):
            await client.panel.connect(SYSTEM_ID, "0000")
        assert released == [True]


async def test_connect_answer_that_is_not_an_object_is_an_api_error() -> None:
    async def listed(_request: web.Request) -> web.Response:
        return web.json_response([1, 2])

    async for client in serve([("POST", CONNECT_PATH, listed)]):
        with pytest.raises(DaitemApiError, match="expected a JSON object"):
            await client.panel.connect(SYSTEM_ID, "0000")
