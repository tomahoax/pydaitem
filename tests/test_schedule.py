"""Tests for the schedule (recurring arm/disarm) façade, against a real local server.

See test_errors.py for why a local aiohttp server is used instead of a mock library.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable

from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import DaitemClient, DaitemSystem, ScheduleProgram

SYSTEM_ID = 123456
SCHEDULE_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/schedule"
CONNECT_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/connect"
DISCONNECT_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/disconnect"

SCHEDULE_BODY = {
    "globalActivation": True,
    "programs": [
        {"id": 1, "day": "monday", "hour": 22, "minute": 0, "command": True, "groups": [1]}
    ],
    "maxProgramCount": 50,
}


async def connect(_request: web.Request) -> web.Response:
    return web.json_response({"ttmSessionId": "sess", "systemState": "off", "groups": []})


async def disconnect(_request: web.Request) -> web.Response:
    return web.json_response({"status": "OK"})


async def serve(routes: list[tuple[str, str, Callable]]) -> AsyncIterator[DaitemSystem]:
    """Start a local server and return a `DaitemSystem` pointing at it, pre-authenticated."""
    app = web.Application()
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()

    client = DaitemClient(
        "account@example.test", "password", api_base=str(server.make_url("")).rstrip("/")
    )
    # Short-circuit the Keycloak flow: these tests cover the schedule façade only.
    client._state.access_token = "test-token"
    client._state.refresh_token = "test-refresh"
    client._state.token_expires_at = time.monotonic() + 3600
    system = DaitemSystem(client, SYSTEM_ID, "0000")
    try:
        yield system
    finally:
        await client.close()
        await server.close()


async def test_read_schedule_parses_programs_and_opens_a_session() -> None:
    calls: list[str] = []

    async def schedule(_request: web.Request) -> web.Response:
        calls.append("schedule")
        return web.json_response(SCHEDULE_BODY)

    async def connect_tracking(request: web.Request) -> web.Response:
        calls.append("connect")
        return await connect(request)

    async def disconnect_tracking(request: web.Request) -> web.Response:
        calls.append("disconnect")
        return await disconnect(request)

    routes = [
        ("GET", SCHEDULE_PATH, schedule),
        ("POST", CONNECT_PATH, connect_tracking),
        ("POST", DISCONNECT_PATH, disconnect_tracking),
    ]
    async for system in serve(routes):
        result = await system.schedule.read()
        assert result.global_activation is True
        assert result.max_program_count == 50
        assert len(result.programs) == 1

        program = result.programs[0]
        assert program.id == 1
        assert program.day == "monday"
        assert program.hour == 22
        assert program.minute == 0
        assert program.command is True
        assert program.groups == [1]

        # Treated as needing a session, like the widgets endpoint: opened then released.
        assert calls == ["connect", "schedule", "disconnect"]


async def test_update_schedule_program_sends_the_full_payload() -> None:
    received: dict[str, object] = {}

    async def update(request: web.Request) -> web.Response:
        received["body"] = await request.json()
        received["path"] = request.path
        return web.json_response(received["body"])

    routes = [
        ("POST", CONNECT_PATH, connect),
        ("PUT", f"{SCHEDULE_PATH}/1", update),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for system in serve(routes):
        program = ScheduleProgram(
            id=1, day="tuesday", hour=7, minute=30, command=False, groups=[1, 2]
        )
        result = await system.schedule.update_program(program)

        assert received["path"] == f"{SCHEDULE_PATH}/1"
        assert received["body"] == {
            "id": 1,
            "day": "tuesday",
            "hour": 7,
            "minute": 30,
            "command": False,
            "groups": [1, 2],
        }
        assert result.day == "tuesday"
        assert result.hour == 7


async def test_delete_schedule_program_raises_nothing_on_204() -> None:
    async def delete(_request: web.Request) -> web.Response:
        return web.Response(status=204)

    routes = [
        ("POST", CONNECT_PATH, connect),
        ("DELETE", f"{SCHEDULE_PATH}/3", delete),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for system in serve(routes):
        await system.schedule.delete_program(3)  # Must not raise.


async def test_set_schedule_active_sends_the_activate_payload() -> None:
    received: dict[str, object] = {}

    async def activate(request: web.Request) -> web.Response:
        received["body"] = await request.json()
        return web.Response(status=204)

    routes = [
        ("POST", CONNECT_PATH, connect),
        ("PUT", f"{SCHEDULE_PATH}/activate", activate),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for system in serve(routes):
        await system.schedule.set_active(True)
        assert received["body"] == {"activate": True}
