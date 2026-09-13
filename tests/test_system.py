"""Tests for `DaitemSystem`, the semantic façade, against a real local server.

See test_errors.py for why a local aiohttp server is used instead of a mock library.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable

from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import ArmMode, DaitemClient, DaitemSystem

SYSTEM_ID = 123456
USER_PATH = "/topaze/v1/user"
WIDGETS_PATH = f"/topaze/v1/widgets/systems/{SYSTEM_ID}/users/42"
CONNECT_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/connect"
DISCONNECT_PATH = f"/topaze/v5/systems/{SYSTEM_ID}/disconnect"


async def user(_request: web.Request) -> web.Response:
    return web.json_response({"userId": 42})


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
    # Short-circuit the Keycloak flow: these tests cover capability discovery only.
    client._state.access_token = "test-token"
    client._state.refresh_token = "test-refresh"
    client._state.token_expires_at = time.monotonic() + 3600
    system = DaitemSystem(client, SYSTEM_ID, "0000")
    try:
        yield system
    finally:
        await client.close()
        await server.close()


async def test_arm_modes_discovered_when_a_preset_exists() -> None:
    """A defined partial preset is discovered and marks discovery as successful."""

    async def widgets(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "widgets": [
                    {
                        "widgetType": "widget_type_partial_arming",
                        "widgetItems": [{"id": 1, "name": "partial_arming_name_presence"}],
                    }
                ]
            }
        )

    routes = [
        ("GET", USER_PATH, user),
        ("GET", WIDGETS_PATH, widgets),
        ("POST", CONNECT_PATH, connect),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for system in serve(routes):
        modes = await system.capabilities.arm_modes()
        assert modes == frozenset({ArmMode.AWAY, ArmMode.PRESENCE})
        assert system.capabilities.discovered is True


async def test_arm_modes_discovery_blocked_stays_away_only_and_unresolved() -> None:
    """A panel session already held by another device must not look like a resolved
    installation.

    Regression: comparing only the returned frozenset to {AWAY} cannot tell this apart
    from a genuinely away-only installation, which would make a consumer warn on every
    startup of a perfectly normal setup.
    """

    async def busy_connect(_request: web.Request) -> web.Response:
        return web.json_response(
            {"message": "transmitter.connection.sessionalreadyopen", "details": "owner"},
            status=409,
        )

    async for system in serve([("POST", CONNECT_PATH, busy_connect)]):
        modes = await system.capabilities.arm_modes()
        assert modes == frozenset({ArmMode.AWAY})
        assert system.capabilities.discovered is False


async def test_three_presets_are_all_discovered() -> None:
    """Presence plus two other named presets: all three become distinct ArmMode values.

    Regression: only the first non-presence preset used to be captured, silently dropping
    any further one - discovered live against a real installation exposing three presets.
    """

    async def widgets(_request: web.Request) -> web.Response:
        return web.json_response(
            {
                "widgets": [
                    {
                        "widgetType": "widget_type_partial_arming",
                        "widgetItems": [
                            {"id": 0, "name": "partial_arming_name_presence", "groups": [1]},
                            {"id": 1, "name": "partial_arming_name_1", "groups": [1]},
                            {"id": 2, "name": "partial_arming_name_2", "groups": [2]},
                        ],
                    }
                ]
            }
        )

    routes = [
        ("GET", USER_PATH, user),
        ("GET", WIDGETS_PATH, widgets),
        ("POST", CONNECT_PATH, connect),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for system in serve(routes):
        modes = await system.capabilities.arm_modes()
        assert modes == frozenset(
            {ArmMode.AWAY, ArmMode.PRESENCE, ArmMode.PARTIAL, ArmMode.PARTIAL_2}
        )


async def test_arm_groups_sends_the_requested_combination() -> None:
    """Direct per-group control, bypassing named presets entirely."""
    received: dict[str, object] = {}

    async def group_command(request: web.Request) -> web.Response:
        received["body"] = await request.json()
        return web.json_response({"systemState": "group", "groups": [1]})

    routes = [
        ("POST", CONNECT_PATH, connect),
        (
            "POST",
            f"/topaze/v1/action/systems/{SYSTEM_ID}/sendGroupCommand",
            group_command,
        ),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for system in serve(routes):
        status = await system.commands.arm_groups({1: False, 2: True})
        assert status.state == "group"
        assert received["body"] == {
            "groups": [{"id": 1, "active": False}, {"id": 2, "active": True}]
        }


async def test_genuine_away_only_installation_is_marked_discovered() -> None:
    """An installation with no partial preset is resolved, not just defaulted to away."""

    async def no_widgets(_request: web.Request) -> web.Response:
        return web.json_response({"widgets": []})

    routes = [
        ("GET", USER_PATH, user),
        ("GET", WIDGETS_PATH, no_widgets),
        ("POST", CONNECT_PATH, connect),
        ("POST", DISCONNECT_PATH, disconnect),
    ]
    async for system in serve(routes):
        modes = await system.capabilities.arm_modes()
        assert modes == frozenset({ArmMode.AWAY})
        assert system.capabilities.discovered is True
