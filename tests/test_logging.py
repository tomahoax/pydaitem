"""Debug logging: one line per request, one cycle per panel session, and no secret anywhere.

A host application turns these on to understand an edge case after the fact (a busy panel,
a slow release), and its users paste them into public issues.
"""

from __future__ import annotations

import logging
import re
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import DaitemClient, DaitemSystem

SID = 123456
BASE = f"/topaze/v5/systems/{SID}"
CODE = "4321"
TOKEN = "access-token-secret"


async def test_a_session_cycle_reads_as_a_whole_without_secrets(
    caplog: pytest.LogCaptureFixture,
) -> None:
    reads: list[str] = []

    async def state(_request: web.Request) -> web.Response:
        reads.append("state")
        if len(reads) == 1:  # nobody holds the panel yet
            return web.json_response(
                {"message": "status.nottmsessionid", "details": "Failed to get last TTM session"},
                status=403,
            )
        return web.json_response({"systemState": "off", "groups": []})

    async def connect(_request: web.Request) -> web.Response:
        return web.json_response({"ttmSessionId": "ttm-secret", "systemState": "off"})

    async def disconnect(_request: web.Request) -> web.Response:
        return web.json_response({})

    app = web.Application()
    app.router.add_get(f"{BASE}/state", state)
    app.router.add_post(f"{BASE}/connect", connect)
    app.router.add_post(f"{BASE}/disconnect", disconnect)
    server = TestServer(app)
    await server.start_server()
    client = DaitemClient(
        "someone@example.test", "password", api_base=str(server.make_url("")).rstrip("/")
    )
    client._state.access_token = TOKEN
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        with caplog.at_level(logging.DEBUG, logger="pydaitem"):
            await DaitemSystem(client, SID, CODE).panel.read()
            await client.panel.wait_released()
    finally:
        await client.close()
        await server.close()

    lines = [r.getMessage() for r in caplog.records if r.name.startswith("pydaitem")]
    requests = [line for line in lines if " -> HTTP " in line]
    assert [line.split(" in ")[0] for line in requests] == [
        f"GET {BASE}/state -> HTTP 403",
        f"POST {BASE}/connect -> HTTP 200",
        f"POST {BASE}/disconnect -> HTTP 200",
    ]
    # The first read ran before any session, the other two inside the same one.
    tags = [re.search(r"\[session (\w+)\]$", line) for line in requests]
    assert tags[0] is None
    assert len({tag.group(1) for tag in tags[1:] if tag}) == 1 and all(tags[1:])
    assert any("released, held" in line for line in lines)

    text = "\n".join(lines)
    for secret in (CODE, TOKEN, "ttm-secret", "someone@example.test", "password"):
        assert secret not in text, secret


async def test_cache_headers_are_logged_once_per_endpoint(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """How to learn whether the API would answer a conditional request with a 304."""

    async def state(_request: web.Request) -> web.Response:
        return web.json_response({"systemState": "off"}, headers={"ETag": '"v1"'})

    app = web.Application()
    app.router.add_get(f"{BASE}/state", state)
    server = TestServer(app)
    await server.start_server()
    client = DaitemClient("a@example.test", "p", api_base=str(server.make_url("")).rstrip("/"))
    client._state.access_token = TOKEN
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        with caplog.at_level(logging.DEBUG, logger="pydaitem"):
            await client.panel.get_state(SID)
            await client.panel.get_state(SID)
    finally:
        await client.close()
        await server.close()
    lines = [r.getMessage() for r in caplog.records if "cache headers" in r.getMessage()]
    assert lines == ["GET /topaze/v5/systems/{id}/state: cache headers {'ETag': '\"v1\"'}"]
