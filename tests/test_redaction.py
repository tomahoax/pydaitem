"""Redaction: a dump is meant to be attached to a public issue, so a leak is a security bug.

The first test comes from the Home Assistant integration, where this code lived before.
"""

from __future__ import annotations

import json
import time
from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import DaitemClient, DaitemSystem, redact, redact_identifier

SID = 123456
BASE = f"/topaze/v5/systems/{SID}"


def test_redaction_catches_keys_nobody_anticipated() -> None:
    """A renamed field in a raw payload must be redacted on its name, not on a fixed list."""
    payload: dict[str, Any] = {
        "someNewAccessToken": "secret-value",
        "masterCode": "0000",
        "ttmSessionId": "abcdef123456",
        "nested": [{"userPassword": "hunter2"}],
        "serialNumber": "SN-0123456789",
        "systemState": "off",
        "session_busy": True,
    }

    redacted = redact(payload)

    assert redacted["someNewAccessToken"] == "***"
    assert redacted["masterCode"] == "***"
    assert redacted["ttmSessionId"] == "***"
    assert redacted["nested"][0]["userPassword"] == "***"
    # Identifiers stay correlatable, values that carry no identity stay intact.
    assert redacted["serialNumber"] == "SN-...789"
    assert redacted["systemState"] == "off"
    assert redacted["session_busy"] is True
    assert payload["masterCode"] == "0000"  # a copy: the caller's data is untouched


def test_camera_access_and_home_details_are_redacted() -> None:
    """Fragments the Home Assistant integration added once cameras and contacts came in."""
    payload = {
        "dahuaInfo": {"deeplink": "vendor-secret", "playInfo": {"url": "rtsp://x"}},
        "channelId": "ch-1",
        "deviceUid": "UID-0123456789",
        "label": "Portail Dupont",
        "phoneNumber": "+33600000000",
        "address": "1 rue de la Paix",
        "city": "Paris-Centre",
        "transmitterId": "TT-0123456789",
    }
    redacted = redact(payload)
    assert redacted["dahuaInfo"]["deeplink"] == "***"
    assert redacted["dahuaInfo"]["playInfo"] == "***"
    assert redacted["channelId"] == "***"
    for key in ("deviceUid", "label", "phoneNumber", "address", "city", "transmitterId"):
        assert redacted[key] != payload[key] and "..." in redacted[key], key


def test_redaction_can_run_twice() -> None:
    """A host application may redact again what the library already redacted."""
    payload = {"email": "someone@example.com", "token": "t", "name": "Maison", "id": "Ab"}
    once = redact(payload)
    assert redact(once) == once
    assert redact_identifier(redact_identifier("SN-0123456789")) == "SN-...789"


def test_the_apps_preset_names_stay_readable() -> None:
    """A report about a missing arming mode needs the preset names the panel sent."""
    widget = {
        "widgetItems": [
            {"id": 0, "name": "partial_arming_name_presence"},
            {"id": 1, "name": "Nuit chez Marie"},  # a name the installer chose
        ]
    }
    items = redact(widget)["widgetItems"]
    assert items[0]["name"] == "partial_arming_name_presence"
    assert items[1]["name"] == "Nui...rie"


def test_short_identifiers_and_long_strings() -> None:
    assert redact_identifier("Bob") == "***"
    assert redact_identifier("") == ""
    long = redact({"details": "x" * 2000})["details"]
    assert len(long) < 400 and long.startswith("x" * 256)


async def test_collect_raw_is_redacted_unless_told_otherwise() -> None:
    async def state(_request: web.Request) -> web.Response:
        return web.json_response({"systemState": "off", "ttmSessionId": "sess-123456"})

    async def configuration(_request: web.Request) -> web.Response:
        return web.json_response(
            {"central": {"serialNumber": "SN-0123456789"}, "userEmail": "someone@example.com"}
        )

    async def busy(_request: web.Request) -> web.Response:
        return web.json_response(
            {"message": "transmitter.connection.sessionalreadyopen", "details": "Marie Dupont"},
            status=409,
        )

    async def no_session(_request: web.Request) -> web.Response:
        return web.json_response(
            {"message": "status.nottmsessionid", "details": "Failed to get last TTM session"},
            status=403,
        )

    app = web.Application()
    app.router.add_get(f"{BASE}/state", state)
    app.router.add_get(f"/topaze/v2/systems/{SID}/configuration", configuration)
    app.router.add_post(f"{BASE}/connect", busy)
    for path in (
        f"{BASE}/automatisms",
        f"/topaze/v1/systems/{SID}/cameras",
        f"/topaze/v6/systems/{SID}/videos",
        f"/topaze/v6/systems/{SID}/scenarios",
        f"{BASE}/schedule",
    ):
        app.router.add_get(path, no_session)
    server = TestServer(app)
    await server.start_server()
    client = DaitemClient("a@example.test", "p", api_base=str(server.make_url("")).rstrip("/"))
    client._state.access_token = "token"
    client._state.token_expires_at = time.monotonic() + 3600
    system = DaitemSystem(client, SID, "0000")
    try:
        dump = await system.collect_raw(logbook_entries=0)
        text = json.dumps(dump)
        for secret in ("sess-123456", "SN-0123456789", "someone@example.com", "Marie Dupont"):
            assert secret not in text, secret
        assert dump["redacted"] is True
        assert dump["payloads"]["state"]["systemState"] == "off"
        assert "DaitemSessionBusyError" in dump["errors"]["scenarios"]

        raw = await system.collect_raw(logbook_entries=0, redact=False)
        assert raw["payloads"]["state"]["ttmSessionId"] == "sess-123456"
        assert "Marie Dupont" in raw["errors"]["scenarios"]
    finally:
        await client.close()
        await server.close()
