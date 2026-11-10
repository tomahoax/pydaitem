"""The panel session is released whatever ends a block, against a real local server.

The panel accepts one session at a time across all accounts: one left open locks the mobile
app out until it expires, and every later command fails with 409.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Callable

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import (
    DaitemApiError,
    DaitemClient,
    DaitemConnectionError,
    DaitemError,
    DaitemSessionBusyError,
    DaitemUsageError,
)
from pydaitem.client import panel

SYSTEM_ID = 123456
BASE = f"/topaze/v5/systems/{SYSTEM_ID}"
OPEN = {"ttmSessionId": "sess", "systemState": "off", "groups": []}


class Panel:
    """A fake panel that, like the real one, refuses a second session with 409."""

    def __init__(
        self,
        *,
        connect_delay: float = 0.0,
        answer: object = None,
        deferred: bool = False,
        disconnect_status: int = 200,
    ) -> None:
        self.connect_delay = connect_delay
        self.answer = OPEN if answer is None else answer
        self.deferred = deferred
        self.disconnect_status = disconnect_status
        self.open = False
        self.connects = 0
        self.disconnects = 0
        self.refused = 0

    async def connect(self, _request: web.Request) -> web.Response:
        self.connects += 1
        if self.open:
            self.refused += 1
            return web.json_response(
                {"message": "transmitter.connection.sessionalreadyopen"}, status=409
            )
        self.open = True
        await asyncio.sleep(self.connect_delay)
        if self.deferred:
            location = f"/v5/systems/{SYSTEM_ID}/connect/tx-1"
            return web.json_response(
                {"message": "ACCEPTED"}, status=202, headers={"Location": location}
            )
        return web.json_response(self.answer)

    async def disconnect(self, _request: web.Request) -> web.Response:
        self.disconnects += 1
        self.open = False
        if self.disconnect_status != 200:
            return web.json_response({"message": "unexpected.error"}, status=500)
        return web.json_response({"status": "OK"})

    async def state(self, _request: web.Request) -> web.Response:
        await asyncio.sleep(0.01)
        return web.json_response({"systemState": "off", "groups": []})


async def serve(
    fake: Panel, *, timeout: float = 5.0, extra: list[tuple[str, str, Callable]] | None = None
) -> AsyncIterator[DaitemClient]:
    app = web.Application()
    app.router.add_post(f"{BASE}/connect", fake.connect)
    app.router.add_post(f"{BASE}/disconnect", fake.disconnect)
    app.router.add_get(f"{BASE}/state", fake.state)
    for method, path, handler in extra or []:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()
    client = DaitemClient(
        "account@example.test",
        "password",
        api_base=str(server.make_url("")).rstrip("/"),
        timeout=timeout,
    )
    client._state.access_token = "test-token"
    client._state.refresh_token = "test-refresh"
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        yield client
    finally:
        await client.close()
        await server.close()


async def test_a_lost_connect_answer_releases_the_session() -> None:
    """The panel opened the session, but its answer timed out on the way back."""
    fake = Panel(connect_delay=0.5)
    async for client in serve(fake, timeout=0.1):
        with pytest.raises(DaitemConnectionError):
            async with client.panel.session(SYSTEM_ID, "0000"):
                pytest.fail("the block must not run")
        await client.panel.wait_released()
        assert fake.disconnects == 1 and not fake.open


async def test_a_caller_cancelled_during_connect_releases_the_session() -> None:
    """A Home Assistant timeout around a read cancels the task while connect is in flight."""
    fake = Panel(connect_delay=0.5)
    async for client in serve(fake):
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1):
                await client.panel.connect(SYSTEM_ID, "0000")
        await client.panel.wait_released()
        assert fake.disconnects == 1 and not fake.open


async def test_a_caller_cancelled_inside_the_block_still_releases() -> None:
    fake = Panel()
    async for client in serve(fake):
        with pytest.raises(TimeoutError):
            async with asyncio.timeout(0.1), client.panel.session(SYSTEM_ID, "0000"):
                await asyncio.sleep(1)
        await client.panel.wait_released()
        assert fake.disconnects == 1 and not fake.open


async def test_a_connect_answer_the_models_cannot_read_releases_the_session() -> None:
    fake = Panel(answer={"ttmSessionId": "sess", "systemState": "off", "groups": [{"x": 1}]})
    async for client in serve(fake):
        with pytest.raises(DaitemApiError, match="unexpected answer"):
            await client.panel.connect(SYSTEM_ID, "0000")
        assert fake.disconnects == 1 and not fake.open
        assert client.panel.ttm_session_id is None


async def test_a_refused_connect_releases_nothing() -> None:
    """A 409 means another device holds the panel: disconnecting could close its session."""
    fake = Panel()
    fake.open = True
    async for client in serve(fake):
        with pytest.raises(DaitemSessionBusyError):
            await client.panel.connect(SYSTEM_ID, "0000")
        assert fake.disconnects == 0


async def test_a_deferred_connect_ending_oddly_is_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status the poller does not know ends it, and the panel may still open the session."""
    monkeypatch.setattr(panel, "CONNECT_POLL_INTERVAL", 0.0)

    async def poll(_request: web.Request) -> web.Response:
        return web.json_response({"status": "IN_PROGRESS"})

    fake = Panel(deferred=True)
    async for client in serve(fake, extra=[("GET", f"{BASE}/connect/tx-1", poll)]):
        with pytest.raises(DaitemApiError):
            await client.panel.connect(SYSTEM_ID, "0000")
        assert fake.disconnects == 1 and not fake.open


async def test_concurrent_blocks_on_one_client_wait_for_each_other() -> None:
    """A poll and a command overlapping must not refuse each other with 409."""
    fake = Panel()
    async for client in serve(fake):

        async def hold(client: DaitemClient) -> None:
            async with client.panel.session(SYSTEM_ID, "0000"):
                await asyncio.sleep(0.05)

        await asyncio.gather(hold(client), hold(client), hold(client))
        await client.panel.wait_released()
        assert fake.refused == 0 and fake.connects == fake.disconnects == 3


async def test_a_session_inside_a_session_is_refused_rather_than_deadlocked() -> None:
    fake = Panel()
    async for client in serve(fake):
        with pytest.raises(DaitemError, match="already open in this task"):
            async with (
                client.panel.session(SYSTEM_ID, "0000"),
                client.panel.session(SYSTEM_ID, "0000"),
            ):
                pytest.fail("the inner block must not run")
        await client.panel.wait_released()
        assert fake.disconnects == 1 and not fake.open


async def test_a_failed_disconnect_still_forgets_the_session_id() -> None:
    fake = Panel(disconnect_status=500)
    async for client in serve(fake):
        async with client.panel.session(SYSTEM_ID, "0000"):
            assert client.panel.ttm_session_id == "sess"
        await client.panel.wait_released()
        assert client.panel.ttm_session_id is None


async def test_a_closed_client_opens_no_new_http_session() -> None:
    fake = Panel()
    async for client in serve(fake):
        await client.close()
        with pytest.raises(DaitemUsageError, match="closed"):
            await client.panel.get_state(SYSTEM_ID)


async def test_a_slow_poll_is_cut_short_at_the_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Retries of one poll must not run past the deadline while the panel may be held."""
    monkeypatch.setattr(panel, "CONNECT_POLL_TIMEOUT", 0.2)

    async def slow(_request: web.Request) -> web.Response:
        await asyncio.sleep(2)
        return web.json_response({"status": "PENDING"})

    fake = Panel(deferred=True)
    async for client in serve(fake, extra=[("GET", f"{BASE}/connect/tx-1", slow)]):
        started = time.monotonic()
        with pytest.raises(DaitemConnectionError, match="still pending"):
            await client.panel.connect(SYSTEM_ID, "0000")
        assert time.monotonic() - started < 1.5
        assert fake.disconnects == 1


async def test_a_poll_answer_that_is_not_a_job_is_an_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(panel, "CONNECT_POLL_INTERVAL", 0.0)

    async def listed(_request: web.Request) -> web.Response:
        return web.json_response(["PENDING"])

    fake = Panel(deferred=True)
    async for client in serve(fake, extra=[("GET", f"{BASE}/connect/tx-1", listed)]):
        with pytest.raises(DaitemApiError, match="not a job"):
            await client.panel.connect(SYSTEM_ID, "0000")
