"""The façade's reads beyond the alarm, and the automation command, against a local server.

What matters here is the session discipline: the panel accepts one session at a time,
across all accounts, so reading automations, cameras and clips must open at most one, and
none when the reads do not need it.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import (
    Automatism,
    DaitemApiError,
    DaitemClient,
    DaitemError,
    DaitemForbiddenError,
    DaitemSystem,
)
from pydaitem.client import logbook

SID = 123456
BASE = f"/topaze/v5/systems/{SID}"
NO_SESSION = {"message": "status.nottmsessionid", "details": "Failed to get last TTM session"}
GATE = {"id": "gate-1", "category": "GATE", "availableCommands": ["PULSE"], "label": "Portail"}


async def serve(
    routes: dict[tuple[str, str], Callable[[web.Request], web.Response]],
) -> AsyncIterator[tuple[DaitemSystem, list[str]]]:
    calls: list[str] = []

    def wrap(name: str, handler: Callable[[web.Request], web.Response]) -> Callable:
        async def recorded(request: web.Request) -> web.Response:
            calls.append(name)
            return handler(request)

        return recorded

    app = web.Application()
    for (method, path), handler in routes.items():
        app.router.add_route(method, path, wrap(path.rsplit("/", 1)[-1], handler))
    server = TestServer(app)
    await server.start_server()
    client = DaitemClient(
        "account@example.test", "password", api_base=str(server.make_url("")).rstrip("/")
    )
    client._state.access_token = "test-token"
    client._state.refresh_token = "test-refresh"
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        yield DaitemSystem(client, SID, "0000"), calls
    finally:
        await client.close()
        await server.close()


def answer(body: object, status: int = 200) -> Callable[[web.Request], web.Response]:
    return lambda _request: web.json_response(body, status=status)


def needs_session(body: object, sessions: list[bool]) -> Callable[[web.Request], web.Response]:
    """Answer only while a session is open, as the state endpoint does."""

    def handler(_request: web.Request) -> web.Response:
        if not sessions or not sessions[-1]:
            return web.json_response(NO_SESSION, status=500)
        return web.json_response(body)

    return handler


def session_routes(sessions: list[bool]) -> dict[tuple[str, str], Callable]:
    def connect(_request: web.Request) -> web.Response:
        sessions.append(True)
        return web.json_response({"ttmSessionId": "sess", "systemState": "off"})

    def disconnect(_request: web.Request) -> web.Response:
        sessions.append(False)
        return web.json_response({"status": "OK"})

    return {("POST", f"{BASE}/connect"): connect, ("POST", f"{BASE}/disconnect"): disconnect}


async def test_extras_read_without_a_session_when_none_is_needed() -> None:
    routes = {
        ("GET", f"{BASE}/automatisms"): answer({"automatisms": [GATE]}),
        ("GET", f"/topaze/v1/systems/{SID}/cameras"): answer({"cameras": []}),
        ("GET", f"/topaze/v6/systems/{SID}/videos"): answer({"videos": []}),
    }
    async for system, calls in serve(routes):
        extras = await system.read_extras()
        assert [a.id for a in extras.automatisms or []] == ["gate-1"]
        assert extras.cameras == [] and extras.clips == [] and extras.errors == {}
        assert "connect" not in calls


async def test_extras_open_one_session_for_every_read_that_needs_it() -> None:
    sessions: list[bool] = []
    routes = {
        **session_routes(sessions),
        ("GET", f"{BASE}/automatisms"): needs_session({"automatisms": [GATE]}, sessions),
        ("GET", f"/topaze/v1/systems/{SID}/cameras"): needs_session({"cameras": []}, sessions),
        ("GET", f"/topaze/v6/systems/{SID}/videos"): answer({"videos": []}),
    }
    async for system, calls in serve(routes):
        extras = await system.read_extras()
        await system.client.panel.wait_released()
        assert extras.automatisms and extras.cameras == [] and extras.errors == {}
        assert calls.count("connect") == 1
        assert calls.count("disconnect") == 1


async def test_one_failed_read_does_not_hide_the_others() -> None:
    routes = {
        ("GET", f"{BASE}/automatisms"): answer({"automatisms": [GATE]}),
        ("GET", f"/topaze/v1/systems/{SID}/cameras"): answer({"cameras": []}),
        ("GET", f"/topaze/v6/systems/{SID}/videos"): answer({"message": "Access is denied"}, 403),
    }
    async for system, _ in serve(routes):
        extras = await system.read_extras()
        assert extras.automatisms is not None and extras.clips is None
        assert isinstance(extras.errors["clips"], DaitemForbiddenError)


async def test_busy_panel_is_reported_per_read() -> None:
    routes = {
        ("POST", f"{BASE}/connect"): answer(
            {"message": "transmitter.connection.sessionalreadyopen", "details": "owner"}, 409
        ),
        ("GET", f"{BASE}/automatisms"): answer(NO_SESSION, 500),
        ("GET", f"/topaze/v1/systems/{SID}/cameras"): answer({"cameras": []}),
        ("GET", f"/topaze/v6/systems/{SID}/videos"): answer({"videos": []}),
    }
    async for system, _ in serve(routes):
        extras = await system.read_extras()
        assert extras.automatisms is None and extras.cameras == []
        assert "automatisms" in extras.errors and "cameras" not in extras.errors


async def test_latest_clip_is_the_newest_whatever_the_order() -> None:
    clips = {
        "videos": [
            {"id": "old", "timestamp": 1_600_000_000},
            {"id": "new", "timestamp": 1_700_000_000},
            {"id": "undated"},
        ]
    }
    routes = {
        ("GET", f"{BASE}/automatisms"): answer({}),
        ("GET", f"/topaze/v1/systems/{SID}/cameras"): answer({}),
        ("GET", f"/topaze/v6/systems/{SID}/videos"): answer(clips),
    }
    async for system, _ in serve(routes):
        extras = await system.read_extras()
        assert extras.latest_clip is not None and extras.latest_clip.id == "new"


async def test_automation_command_runs_inside_a_session() -> None:
    sessions: list[bool] = []
    open_during_command: list[bool] = []

    def command(_request: web.Request) -> web.Response:
        open_during_command.append(bool(sessions) and sessions[-1])
        return web.json_response({})

    routes = {
        **session_routes(sessions),
        ("POST", f"{BASE}/automatisms/gate-1/command"): command,
    }
    async for system, calls in serve(routes):
        await system.automation.command(Automatism.from_json(GATE), "PULSE")
        await system.client.panel.wait_released()
        assert calls == ["connect", "command", "disconnect"]
        assert open_during_command == [True]


async def test_automation_command_it_does_not_list_is_refused_before_sending() -> None:
    async for system, calls in serve({}):
        gate = Automatism.from_json(GATE)
        with pytest.raises(DaitemError, match="does not accept ON"):
            await system.automation.command(gate, "ON")
        assert calls == []


async def test_position_needs_a_position() -> None:
    async for system, calls in serve({}):
        shutter = Automatism.from_json({"id": "s", "availableCommands": ["POSITION"]})
        with pytest.raises(DaitemError, match="needs a position"):
            await system.automation.command(shutter, "POSITION")
        assert calls == []


async def test_a_position_goes_only_with_position() -> None:
    """The app never sends a position with another command: real equipment gets none."""
    async for system, calls in serve({}):
        shutter = Automatism.from_json({"id": "s", "availableCommands": ["ON", "POSITION"]})
        with pytest.raises(DaitemError, match="only goes with POSITION"):
            await system.automation.command(shutter, "ON", position=50)
        assert calls == []


async def test_logbook_entries_are_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logbook, "LOGBOOK_POLL_INTERVAL", 0.0)

    def create(_request: web.Request) -> web.Response:
        return web.json_response(
            {"message": "ACCEPTED"},
            status=202,
            headers={"Location": f"/v5/systems/{SID}/logbook/j1"},
        )

    entry = {
        "date": "2026-09-07T15:22",
        "title": "logEvent.36.label2",
        "details": [{"message": "m"}],
    }
    routes = {
        ("POST", f"{BASE}/logbook"): create,
        ("GET", f"{BASE}/logbook/j1"): answer(
            {"status": "request_status_done", "response": [entry]}
        ),
    }
    async for system, _ in serve(routes):
        (log,) = await system.logbook.read()
        assert log.title == "logEvent.36.label2" and log.details == [{"message": "m"}]
        assert log.when is not None and log.when.hour == 15


async def test_logbook_session_covers_the_job_creation_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Waiting for the job never holds the panel, and the job is created once."""
    monkeypatch.setattr(logbook, "LOGBOOK_POLL_INTERVAL", 0.0)
    sessions: list[bool] = []
    open_during_poll: list[bool] = []

    def create(_request: web.Request) -> web.Response:
        if not sessions or not sessions[-1]:
            return web.json_response(NO_SESSION, status=500)
        headers = {"Location": f"/v5/systems/{SID}/logbook/j1"}
        return web.json_response({"message": "ACCEPTED"}, status=202, headers=headers)

    def poll(_request: web.Request) -> web.Response:
        open_during_poll.append(bool(sessions) and sessions[-1])
        return web.json_response({"status": "request_status_done", "response": []})

    routes = {
        **session_routes(sessions),
        ("POST", f"{BASE}/logbook"): create,
        ("GET", f"{BASE}/logbook/j1"): poll,
    }
    async for system, calls in serve(routes):
        assert await system.logbook.read() == []
        assert calls == ["logbook", "connect", "logbook", "disconnect", "j1"]
        assert open_during_poll == [False]


async def test_collect_raw_keeps_each_answer_and_each_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logbook, "LOGBOOK_POLL_INTERVAL", 0.0)
    gate = {"automatisms": [GATE]}
    routes = {
        ("GET", f"{BASE}/state"): answer({"systemState": "off"}),
        ("GET", f"/topaze/v2/systems/{SID}/configuration"): answer({"central": {}}),
        ("GET", f"{BASE}/automatisms"): answer(gate),
        ("GET", f"/topaze/v1/systems/{SID}/cameras"): answer({"cameras": []}),
        ("GET", f"/topaze/v6/systems/{SID}/videos"): answer({"message": "Access is denied"}, 403),
        ("GET", "/topaze/v1/user"): answer({"userId": 42}),
        ("GET", f"/topaze/v1/widgets/systems/{SID}/users/42"): answer({"widgets": []}),
        ("GET", f"/topaze/v6/systems/{SID}/scenarios"): answer({"scenarios": []}),
        ("GET", f"{BASE}/schedule"): answer({"programs": []}),
        ("POST", "/topaze/configuration/getConfiguration"): answer(
            {"system": {"transmitterId": "tx-1"}}
        ),
        ("POST", "/topaze/installation/isConnected"): answer({"isConnected": True}),
        ("POST", f"{BASE}/logbook"): answer({"message": "Access is denied"}, 403),
    }
    async for system, calls in serve(routes):
        dump = await system.collect_raw(redact=False)
        assert dump["payloads"]["automatisms"] == gate
        assert dump["payloads"]["installation"]["transmitter_connected"] is True
        assert dump["errors"]["videos"].startswith("DaitemForbiddenError")
        assert dump["errors"]["logbook"].startswith("DaitemForbiddenError")
        assert "connect" not in calls


async def test_collect_raw_waits_for_the_logbook_outside_the_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logbook, "LOGBOOK_POLL_INTERVAL", 0.0)
    sessions: list[bool] = []
    open_during_poll: list[bool] = []

    def create(_request: web.Request) -> web.Response:
        if not sessions or not sessions[-1]:
            return web.json_response(NO_SESSION, status=500)
        headers = {"Location": f"/v5/systems/{SID}/logbook/j1"}
        return web.json_response({"message": "ACCEPTED"}, status=202, headers=headers)

    def poll(_request: web.Request) -> web.Response:
        open_during_poll.append(bool(sessions) and sessions[-1])
        return web.json_response({"status": "request_status_done", "response": [{"date": "d"}]})

    routes = {
        **session_routes(sessions),
        ("POST", f"{BASE}/logbook"): create,
        ("GET", f"{BASE}/logbook/j1"): poll,
    }
    async for system, calls in serve(routes):
        dump = await system.collect_raw(logbook_entries=1)
        assert dump["payloads"]["logbook"] == {"count": 1, "latest": [{"date": "d"}]}
        assert open_during_poll == [False]
        assert calls.count("logbook") == 2  # once without a session, once inside it


async def test_collect_raw_keeps_the_record_when_the_connectivity_check_fails() -> None:
    routes = {
        ("POST", "/topaze/configuration/getConfiguration"): answer(
            {"system": {"transmitterId": "tx-1"}}
        ),
        ("POST", "/topaze/installation/isConnected"): answer({"message": "boom"}, 500),
    }
    async for system, _ in serve(routes):
        dump = await system.collect_raw(redact=False)
        installation = dump["payloads"]["installation"]
        assert installation["record"] == {"system": {"transmitterId": "tx-1"}}
        assert installation["transmitter_connected"].startswith("Daitem")


async def test_video_reads_open_a_session_only_when_needed() -> None:
    sessions: list[bool] = []
    routes = {
        **session_routes(sessions),
        ("GET", f"/topaze/v1/systems/{SID}/cameras"): needs_session(
            {"cameras": [{"id": 7, "name": "Garden"}]}, sessions
        ),
        ("GET", f"/topaze/v6/systems/{SID}/videos"): answer({"videos": [{"id": "f1"}]}),
    }
    async for system, calls in serve(routes):
        (clip,) = await system.video.clips()
        assert clip.id == "f1" and "connect" not in calls
        (camera,) = await system.video.cameras()
        await system.client.panel.wait_released()
        assert camera.name == "Garden"
        assert calls.count("connect") == calls.count("disconnect") == 1


async def test_panel_inventory_and_automation_reads() -> None:
    routes = {
        ("GET", f"{BASE}/state"): answer({"systemState": "on"}),
        ("GET", f"/topaze/v2/systems/{SID}/configuration"): answer(
            {"central": {"type": "INTRUSION"}}
        ),
        ("GET", f"{BASE}/automatisms"): answer({"automatisms": [GATE]}),
    }
    async for system, calls in serve(routes):
        assert (await system.panel.read()).is_armed
        assert (await system.inventory.read()).central_type == "INTRUSION"
        assert [a.id for a in await system.automation.read()] == ["gate-1"]
        assert "connect" not in calls


async def test_transmitter_online_reads_the_record_with_the_accounts_role() -> None:
    bodies: list[object] = []

    async def configuration(request: web.Request) -> web.Response:
        bodies.append(await request.json())
        return web.json_response({"transmitterId": "tx-1", "centralId": "c-1"})

    async def connected(request: web.Request) -> web.Response:
        bodies.append(await request.json())
        return web.json_response({"isConnected": False})

    app = web.Application()

    async def systems(_request: web.Request) -> web.Response:
        return web.json_response([{"id": SID, "role": 0}])

    app.router.add_get("/topaze/v5/systems", systems)
    app.router.add_post("/topaze/configuration/getConfiguration", configuration)
    app.router.add_post("/topaze/installation/isConnected", connected)
    async for system in _serve_app(app):
        assert await system.panel.transmitter_online() is False
        assert await system.panel.transmitter_online() is False  # id kept: one record read
        assert bodies == [
            {"systemId": SID, "role": 0},
            {"transmitterId": "tx-1"},
            {"transmitterId": "tx-1"},
        ]


async def test_transmitter_online_finds_a_nested_transmitter_id() -> None:
    app = web.Application()

    async def systems(_request: web.Request) -> web.Response:
        return web.json_response([{"id": SID, "role": 0}])

    async def configuration(_request: web.Request) -> web.Response:
        return web.json_response({"system": {"transmitterId": "tx-9"}})

    async def connected(request: web.Request) -> web.Response:
        assert await request.json() == {"transmitterId": "tx-9"}
        return web.json_response({"isConnected": True})

    app.router.add_get("/topaze/v5/systems", systems)
    app.router.add_post("/topaze/configuration/getConfiguration", configuration)
    app.router.add_post("/topaze/installation/isConnected", connected)
    async for system in _serve_app(app):
        assert await system.panel.transmitter_online() is True


async def test_a_record_without_transmitter_id_is_an_api_error() -> None:
    """The API's answer is at fault, not the call: a consumer reads it as `DaitemApiError`."""
    app = web.Application()

    async def systems(_request: web.Request) -> web.Response:
        return web.json_response([{"id": SID, "role": 0}])

    async def configuration(_request: web.Request) -> web.Response:
        return web.json_response({"centralId": "c-1"})

    app.router.add_get("/topaze/v5/systems", systems)
    app.router.add_post("/topaze/configuration/getConfiguration", configuration)
    async for system in _serve_app(app):
        with pytest.raises(DaitemApiError, match="no transmitter id"):
            await system.panel.transmitter_online()


async def test_wait_settled_reads_until_the_exit_delay_ends() -> None:
    states = iter(["tempo", "tempo", "on"])
    routes = {("GET", f"{BASE}/state"): lambda _r: web.json_response({"systemState": next(states)})}
    async for system, calls in serve(routes):
        status = await system.panel.wait_settled(interval=0)
        assert status.state == "on" and calls.count("state") == 3


async def test_wait_settled_gives_up_after_its_timeout() -> None:
    routes = {("GET", f"{BASE}/state"): answer({"systemState": "tempo"})}
    async for system, _ in serve(routes):
        assert (await system.panel.wait_settled(timeout=0, interval=0)).is_arming


async def test_scenario_runs_inside_a_session() -> None:
    sessions: list[bool] = []
    open_during_run: list[bool] = []

    def start(_request: web.Request) -> web.Response:
        open_during_run.append(bool(sessions) and sessions[-1])
        return web.json_response({"systemState": "off", "commandStatus": "CMD_OK"})

    routes = {
        **session_routes(sessions),
        ("GET", f"/topaze/v6/systems/{SID}/scenarios"): answer(
            {"scenarios": [{"id": 4, "name": "Night", "triggerType": "MANUAL"}]}
        ),
        ("POST", f"/topaze/v1/action/systems/{SID}/startScenarioWidgetCommand/4"): start,
    }
    async for system, calls in serve(routes):
        (scenario,) = await system.scenarios.read()
        status = await system.scenarios.run(scenario)
        await system.client.panel.wait_released()
        assert status.state == "off" and open_during_run == [True]
        assert calls[-3:] == ["connect", "4", "disconnect"]


async def _serve_app(app: web.Application) -> AsyncIterator[DaitemSystem]:
    server = TestServer(app)
    await server.start_server()
    client = DaitemClient(
        "account@example.test", "password", api_base=str(server.make_url("")).rstrip("/")
    )
    client._state.access_token = "test-token"
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        yield DaitemSystem(client, SID, "0000")
    finally:
        await client.close()
        await server.close()


async def test_an_answer_shaped_otherwise_fails_its_read_only() -> None:
    """An answer of an unexpected shape must not hide the other lists."""
    routes = {
        ("GET", f"{BASE}/automatisms"): answer({"automatisms": [GATE]}),
        ("GET", f"/topaze/v1/systems/{SID}/cameras"): answer({"cameras": [{"id": "cam-a"}]}),
        ("GET", f"/topaze/v6/systems/{SID}/videos"): answer({"videos": []}),
    }
    async for system, _ in serve(routes):
        extras = await system.read_extras()
        assert extras.cameras is None and "cameras" in extras.errors
        assert extras.automatisms is not None and extras.clips == []
        with pytest.raises(DaitemApiError):
            await system.video.cameras()
