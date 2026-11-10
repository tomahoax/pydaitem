"""Every client method sends the call the API map describes, against a real local server.

One recording server answers every path, so each case checks the method, the path and the
body actually sent, then what the method made of the answer. Payloads follow the models in
`docs/api/openapi.yaml`.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import (
    DaitemApiError,
    DaitemBadCodeError,
    DaitemClient,
    DaitemError,
    DaitemUsageError,
)
from pydaitem.client import logbook, video
from pydaitem.const.devices import InstallerAccess, PanelMode, PpmsAlert
from pydaitem.models import Automatism, Clip

SID = 123456


class Recorder:
    """Answers every request with the next canned reply, and records what it received."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.replies: dict[tuple[str, str], list[web.Response]] = {}
        self.drop = False

    def reply(self, method: str, path: str, *responses: web.Response) -> None:
        self.replies[(method, path)] = list(responses)

    async def handle(self, request: web.Request) -> web.Response:
        body = await request.json() if request.can_read_body else None
        self.calls.append((request.method, request.path, body))
        if self.drop:
            assert request.transport is not None
            request.transport.close()
            return web.Response()
        queue = self.replies.get((request.method, request.path))
        if queue:
            return queue.pop(0) if len(queue) > 1 else queue[0]
        return web.json_response({})


@pytest.fixture
async def served() -> AsyncIterator[tuple[DaitemClient, Recorder]]:
    recorder = Recorder()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", recorder.handle)
    server = TestServer(app)
    await server.start_server()
    client = DaitemClient(
        "account@example.test", "password", api_base=str(server.make_url("")).rstrip("/")
    )
    client._state.access_token = "test-token"
    client._state.refresh_token = "test-refresh"
    client._state.token_expires_at = time.monotonic() + 3600
    try:
        yield client, recorder
    finally:
        await client.close()
        await server.close()


CLIP = Clip(id="f1", category="CAMERA", device_uid="cam-9")

Call = Callable[[DaitemClient], Awaitable[Any]]

CASES: list[tuple[str, Call, str, str, Any]] = [
    # (case, call, method, path, body sent)
    (
        "automation command",
        lambda c: c.automation.command(SID, "a1", "POSITION", position=40),
        "POST",
        f"/topaze/v5/systems/{SID}/automatisms/a1/command",
        {"type": "POSITION", "position": 40},
    ),
    (
        "automation widget command",
        lambda c: c.automation.widget_command(SID, 7, "launch"),
        "POST",
        f"/topaze/v1/action/systems/{SID}/sendAutomationWidgetCommand",
        {"command": "launch", "id": 7},
    ),
    (
        "delete a clip",
        lambda c: c.video.delete_clip(SID, CLIP),
        "DELETE",
        f"/topaze/v5/systems/{SID}/videos/CAMERA/cam-9/f1",
        None,
    ),
    (
        "scenario create",
        lambda c: c.scenarios.create(SID, {"name": "n", "active": True}),
        "POST",
        f"/topaze/v6/systems/{SID}/scenarios",
        {"name": "n", "active": True},
    ),
    (
        "scenario update",
        lambda c: c.scenarios.update(SID, {"id": 4, "active": False}),
        "PUT",
        f"/topaze/v6/systems/{SID}/scenarios/4",
        {"id": 4, "active": False},
    ),
    (
        "scenario delete",
        lambda c: c.scenarios.delete(SID, 4),
        "DELETE",
        f"/topaze/v6/systems/{SID}/scenarios/4",
        None,
    ),
    (
        "scenario templates",
        lambda c: c.scenarios.templates(SID),
        "GET",
        f"/topaze/v6/systems/{SID}/scenarios/templates",
        None,
    ),
    (
        "scenario actions",
        lambda c: c.scenarios.actions(SID),
        "GET",
        f"/topaze/v6/systems/{SID}/scenarios/actions",
        None,
    ),
    (
        "scenario configuration",
        lambda c: c.scenarios.configuration(SID),
        "GET",
        f"/topaze/v5/systems/{SID}/scenarios/configuration",
        None,
    ),
    (
        "run a scenario",
        lambda c: c.commands.start_scenario(SID, 4),
        "POST",
        f"/topaze/v1/action/systems/{SID}/startScenarioWidgetCommand/4",
        None,
    ),
    (
        "trigger an alert",
        lambda c: c.commands.start_alert(SID, 2),
        "POST",
        f"/topaze/v1/action/systems/{SID}/startAlertWidgetCommand/2",
        None,
    ),
    (
        "PPMS alert",
        lambda c: c.commands.send_ppms(SID, PpmsAlert.ATTACK, True),
        "POST",
        f"/topaze/v1/systems/{SID}/actions/sendPpmsCommand",
        {"type": "ATTACK", "status": "ON"},
    ),
    (
        "switch the panel mode",
        lambda c: c.panel.switch_mode(SID, PanelMode.TEST),
        "POST",
        f"/topaze/v5/systems/{SID}/switchMode/TEST",
        None,
    ),
    (
        "inhibit a device",
        lambda c: c.devices.set_inhibited(SID, "SN1", True),
        "PATCH",
        f"/topaze/v1/systems/{SID}/products/SN1",
        {"isInhibited": True},
    ),
    (
        "firmware update",
        lambda c: c.devices.update_firmware(SID, "SN1", "fw.bin"),
        "POST",
        f"/topaze/v1/systems/{SID}/updateFirmware",
        {"firmwareFileName": "fw.bin", "serialNumber": "SN1"},
    ),
    (
        "rename the installation",
        lambda c: c.devices.rename(SID, "Home"),
        "PUT",
        f"/topaze/v5/systems/{SID}/name",
        {"name": "Home"},
    ),
    (
        "GPRS phone number",
        lambda c: c.devices.set_gprs_phone(SID, "+33600000000"),
        "PUT",
        f"/topaze/v5/systems/{SID}/gprs-phone-number",
        {"phoneNumber": "+33600000000"},
    ),
    ("countries", lambda c: c.devices.countries(), "GET", "/topaze/v5/configuration", None),
    (
        "installation record",
        lambda c: c.devices.get_configuration(SID, role=1),
        "POST",
        "/topaze/configuration/getConfiguration",
        {"systemId": SID, "role": 1},
    ),
    (
        "register for push",
        lambda c: c.notifications.register_push(SID, "dev-1", lang="fr"),
        "POST",
        f"/topaze/v5/systems/{SID}/notifications",
        {"deviceId": "dev-1", "lang": "fr"},
    ),
    (
        "unregister push",
        lambda c: c.notifications.unregister_push(SID, "dev-1"),
        "DELETE",
        f"/topaze/v5/systems/{SID}/notifications",
        {"deviceId": "dev-1"},
    ),
    (
        "push registered",
        lambda c: c.notifications.is_registered(SID),
        "GET",
        f"/topaze/v5/systems/{SID}/notifications/registered",
        None,
    ),
    (
        "unregister all",
        lambda c: c.notifications.unregister_all(SID),
        "DELETE",
        f"/topaze/v5/systems/{SID}/notifications/all",
        None,
    ),
    (
        "list receivers",
        lambda c: c.notifications.list_receivers(SID),
        "GET",
        f"/topaze/v5/systems/{SID}/notifications",
        None,
    ),
    (
        "update a receiver",
        lambda c: c.notifications.update_receiver(SID, 3, {"userType": "OWNER"}),
        "PUT",
        f"/topaze/v5/systems/{SID}/notifications/3",
        {"userType": "OWNER"},
    ),
    (
        "add a contact",
        lambda c: c.notifications.add_contact(
            SID, "Neighbour", "n@example.test", intrusion=True, anomaly=False
        ),
        "POST",
        f"/topaze/v5/systems/{SID}/contacts",
        {
            "username": "Neighbour",
            "email": "n@example.test",
            "alertConfigurationMail": {
                "notificationsMailIntrusion": True,
                "notificationsMailAnomaly": False,
            },
        },
    ),
    (
        "update a contact",
        lambda c: c.notifications.update_contact(SID, 5, "Neighbour", "n@example.test"),
        "PUT",
        f"/topaze/v5/systems/{SID}/contacts/5",
        {"username": "Neighbour", "email": "n@example.test"},
    ),
    (
        "delete a contact",
        lambda c: c.notifications.delete_contact(SID, 5),
        "DELETE",
        f"/topaze/v5/systems/{SID}/contacts/5",
        None,
    ),
    ("list users", lambda c: c.users.list(SID), "GET", f"/topaze/v5/systems/{SID}/users", None),
    (
        "read a code",
        lambda c: c.users.get_code(SID, 2),
        "GET",
        f"/topaze/v5/systems/{SID}/code/2",
        None,
    ),
    (
        "installer access",
        lambda c: c.users.installer_access(SID),
        "GET",
        f"/topaze/v5/systems/{SID}/installer/access",
        None,
    ),
    (
        "set installer access",
        lambda c: c.users.set_installer_access(SID, InstallerAccess.TEST_ONLY),
        "PUT",
        f"/topaze/v5/systems/{SID}/installer/access/TEST_ONLY",
        None,
    ),
    (
        "change installer",
        lambda c: c.users.change_installer(SID, "i@example.test"),
        "PUT",
        f"/topaze/v1/systems/{SID}/installer",
        {"email": "i@example.test"},
    ),
    (
        "create a restricted user",
        lambda c: c.users.create_restricted(SID, {"firstName": "A"}),
        "POST",
        f"/topaze/v1/systems/{SID}/users/restricted",
        {"firstName": "A"},
    ),
    (
        "update the owner",
        lambda c: c.users.update_owner(SID, {"firstName": "A", "country": "FR"}),
        "PUT",
        f"/topaze/v1/systems/{SID}/owner",
        {"firstName": "A", "country": "FR"},
    ),
    (
        "rename a restricted user",
        lambda c: c.users.update_restricted(SID, "A", "B"),
        "PUT",
        f"/topaze/v1/systems/{SID}/restricted",
        {"firstName": "A", "lastName": "B"},
    ),
    (
        "change an e-mail",
        lambda c: c.users.set_email(SID, 8, "u@example.test"),
        "PUT",
        f"/topaze/v1/systems/{SID}/users/8/email",
        {"email": "u@example.test"},
    ),
    (
        "delete a user",
        lambda c: c.users.delete(SID, 8),
        "DELETE",
        f"/topaze/v1/systems/{SID}/users/8",
        None,
    ),
    (
        "change a code",
        lambda c: c.users.set_code(SID, 8, "4321"),
        "PUT",
        f"/topaze/v6/systems/{SID}/users/8/accessCodes",
        {"code": "4321"},
    ),
    (
        "change rights",
        lambda c: c.users.set_rights(SID, 8, {"videos": {"active": False}}),
        "PUT",
        f"/topaze/v6/systems/{SID}/users/8/rights",
        {"videos": {"active": False}},
    ),
    (
        "save the widget layout",
        lambda c: c.widgets.save(SID, 42, [{"id": 1}]),
        "POST",
        f"/topaze/v1/widgets/systems/{SID}/users/42",
        {"widgets": [{"id": 1}]},
    ),
    (
        "save one widget",
        lambda c: c.widgets.save_one(SID, 42, {"id": 1, "isVisible": False}),
        "POST",
        f"/topaze/v1/widgets/1/systems/{SID}/users/42",
        {"id": 1, "isVisible": False},
    ),
    (
        "favourites pop-up",
        lambda c: c.widgets.favorites_popup_shown(SID, 42),
        "GET",
        f"/topaze/v1/systems/{SID}/users/42/isFavoritesMigrationPopupShown",
        None,
    ),
    (
        "hide the pop-up",
        lambda c: c.widgets.hide_favorites_popup(SID, 42),
        "POST",
        f"/topaze/v1/systems/{SID}/users/42/hideFavoritesMigrationPopup",
        None,
    ),
    (
        "Topaze logout",
        lambda c: c.account.topaze_logout("idt"),
        "POST",
        "/topaze/v2/authenticate/logout",
        {"idToken": "idt", "id_token": "idt"},
    ),
    (
        "Topaze logout, first version",
        lambda c: c.account.topaze_logout("idt", v2=False),
        "POST",
        "/topaze/authenticate/logout",
        {"idToken": "idt", "id_token": "idt"},
    ),
    ("upsell", lambda c: c.account.upsell("fr"), "GET", "/topaze/v5/upsell/fr", None),
    (
        "feedback",
        lambda c: c.account.send_feedback(42, "hello"),
        "POST",
        "/topaze/v6/users/42/feedback",
        {"message": "hello"},
    ),
    (
        "add a schedule program",
        lambda c: c.schedule.add_program(SID, {"day": "monday", "hour": 22}),
        "POST",
        f"/topaze/v5/systems/{SID}/schedule",
        {"day": "monday", "hour": 22},
    ),
]


@pytest.mark.parametrize(
    ("call", "method", "path", "body"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
async def test_method_sends_the_mapped_call(
    served: tuple[DaitemClient, Recorder], call: Call, method: str, path: str, body: Any
) -> None:
    client, recorder = served
    await call(client)
    assert recorder.calls == [(method, path, body)]


async def test_automations_are_parsed_leniently(served: tuple[DaitemClient, Recorder]) -> None:
    client, recorder = served
    recorder.reply(
        "GET",
        f"/topaze/v5/systems/{SID}/automatisms",
        web.json_response(
            {
                "automatisms": [
                    {
                        "id": "gate-1",
                        "label": "Portail",
                        "category": "GATE",
                        "availableCommands": ["PULSE"],
                        "state": {"state": "OFF"},
                    },
                    {
                        "id": "shutter-2",
                        "category": "SHUTTER",
                        "availableCommands": ["UP", "DOWN", "STOP", "POSITION"],
                        "state": {"state": "POSITION", "position": 40},
                        "brandNewField": True,
                    },
                ]
            }
        ),
    )
    gate, shutter = await client.automation.list(SID)
    assert gate == Automatism(
        id="gate-1",
        label="Portail",
        category="GATE",
        available_commands=["PULSE"],
        state="OFF",
        raw=gate.raw,
    )
    assert gate.is_on is False and gate.accepts("PULSE") and not gate.accepts("ON")
    assert shutter.position == 40 and shutter.is_on is None
    assert shutter.raw["brandNewField"] is True


async def test_cameras_and_clips_are_parsed(served: tuple[DaitemClient, Recorder]) -> None:
    client, recorder = served
    recorder.reply(
        "GET",
        f"/topaze/v1/systems/{SID}/cameras",
        web.json_response(
            {
                "cameras": [
                    {
                        "id": 3,
                        "uid": "cam-9",
                        "type": "DAHUA",
                        "name": "Entrée",
                        "model": "IPC",
                        "dahuaInfo": {"index": 0, "deeplink": "secret"},
                    }
                ]
            }
        ),
    )
    recorder.reply(
        "GET",
        f"/topaze/v6/systems/{SID}/videos",
        web.json_response(
            {
                "videos": [
                    {
                        "id": "f1",
                        "timestamp": 1_700_000_000_000,
                        "type": "ALARM",
                        "category": "DETECTOR",
                    },
                    {"id": "f2", "timestamp": 1_700_000_000, "type": "ONDEMAND"},
                ]
            }
        ),
    )
    (camera,) = await client.video.list_cameras(SID)
    assert (camera.name, camera.type, camera.status) == ("Entrée", "DAHUA", None)
    assert "secret" not in repr(camera)
    in_ms, in_s = await client.video.list_clips(SID)
    expected = datetime.fromtimestamp(1_700_000_000, tz=UTC)
    assert in_ms.taken_at == expected and in_s.taken_at == expected
    assert in_ms.kind == "ALARM" and in_s.category is None


async def test_clip_is_downloaded_as_bytes(served: tuple[DaitemClient, Recorder]) -> None:
    client, recorder = served
    path = f"/topaze/v5/systems/{SID}/videos/CAMERA/cam-9/f1/mpeg4"
    recorder.reply(
        "GET", path, web.Response(body=b"\x00\x00\x00 ftypmp42", content_type="video/mp4")
    )
    assert client.video.clip_path(SID, CLIP) == path
    assert await client.video.download_clip(SID, CLIP) == b"\x00\x00\x00 ftypmp42"
    # A clip without device uid is fetched with 0 in its place, as the app does.
    assert "/DETECTOR/0/f2/" in client.video.clip_path(SID, Clip(id="f2"))
    # Segments come from the server: escaped, so they cannot move the request elsewhere.
    escaped = client.video.clip_path(SID, Clip(id="../../x", device_uid="a/b"))
    assert escaped.endswith("/DETECTOR/a%2Fb/..%2F..%2Fx/mpeg4")
    # `quote` leaves dots alone and a URL resolves `..`: such a segment is refused.
    for unusable in ("..", "."):
        with pytest.raises(DaitemUsageError, match="not a usable path segment"):
            client.video.clip_path(SID, Clip(id=unusable))


async def test_capture_is_polled_until_done(
    served: tuple[DaitemClient, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "CAPTURE_POLL_INTERVAL", 0.0)
    client, recorder = served
    start = f"/topaze/v5/systems/{SID}/videos/capture/carir/c1"
    recorder.reply(
        "POST",
        start,
        web.json_response(
            {}, status=202, headers={"Location": f"/v5/systems/{SID}/videos/capture/carir/c1/t9"}
        ),
    )
    recorder.reply(
        "GET",
        f"{start}/t9",
        web.json_response({"status": "PENDING"}),
        web.json_response({"status": "DONE", "response": {"filmId": "f3"}}),
    )
    assert await client.video.capture(SID, "c1") == {"filmId": "f3"}


async def test_capture_accepts_a_transaction_id_in_the_body(
    served: tuple[DaitemClient, Recorder],
) -> None:
    client, recorder = served
    start = f"/topaze/v5/systems/{SID}/videos/capture/carir/c1"
    recorder.reply("POST", start, web.json_response({"transactionId": "t9"}))
    assert await client.video.start_capture(SID, "c1") == f"{start}/t9"


async def test_capture_error_is_typed(
    served: tuple[DaitemClient, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(video, "CAPTURE_POLL_INTERVAL", 0.0)
    client, recorder = served
    start = f"/topaze/v5/systems/{SID}/videos/capture/carir/c1"
    recorder.reply("POST", start, web.json_response({"transactionId": "t9"}))
    recorder.reply(
        "GET",
        f"{start}/t9",
        web.json_response(
            {"status": "ERROR", "error": {"message": "transmitter.connection.badpincode"}}
        ),
    )
    with pytest.raises(DaitemBadCodeError):
        await client.video.capture(SID, "c1")


async def test_capture_job_path_outside_captures_is_refused(
    served: tuple[DaitemClient, Recorder],
) -> None:
    client, _ = served
    with pytest.raises(DaitemApiError, match="not a capture job path"):
        await client.video.get_capture("/v1/user")


async def test_logbook_is_read_through_its_job(
    served: tuple[DaitemClient, Recorder], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(logbook, "LOGBOOK_POLL_INTERVAL", 0.0)
    client, recorder = served
    recorder.reply(
        "POST",
        f"/topaze/v5/systems/{SID}/logbook",
        web.json_response(
            {"message": "ACCEPTED"},
            status=202,
            headers={"Location": f"/v5/systems/{SID}/logbook/j1"},
        ),
    )
    entry = {"date": "2026-09-07T15:22", "title": "logEvent.36.label2", "details": []}
    recorder.reply(
        "GET",
        f"/topaze/v5/systems/{SID}/logbook/j1",
        web.json_response({"status": "request_status_pending", "response": None}),
        web.json_response({"status": "request_status_done", "response": [entry]}),
    )
    assert await client.logbook.read(SID) == [entry]


async def test_transmitter_connectivity(served: tuple[DaitemClient, Recorder]) -> None:
    client, recorder = served
    recorder.reply(
        "POST", "/topaze/installation/isConnected", web.json_response({"isConnected": True})
    )
    assert await client.panel.is_connected("tx-1") is True
    assert recorder.calls[-1][2] == {"transmitterId": "tx-1"}


async def test_scenarios_are_parsed(served: tuple[DaitemClient, Recorder]) -> None:
    client, recorder = served
    recorder.reply(
        "GET",
        f"/topaze/v6/systems/{SID}/scenarios",
        web.json_response(
            {
                "scenarios": [
                    {
                        "id": 4,
                        "name": "Arrivée",
                        "active": True,
                        "triggerType": "MANUAL",
                        "actions": [{"type": "ALARM", "rank": 1}],
                    }
                ]
            }
        ),
    )
    (scenario,) = await client.scenarios.list(SID)
    assert (scenario.id, scenario.name, scenario.trigger) == (4, "Arrivée", "MANUAL")
    assert scenario.actions == [{"type": "ALARM", "rank": 1}]


async def test_writes_are_never_replayed(served: tuple[DaitemClient, Recorder]) -> None:
    """A gate command answered by a dropped connection must not be sent twice."""
    client, recorder = served
    recorder.drop = True
    with pytest.raises(DaitemError):
        await client.automation.command(SID, "gate-1", "PULSE")
    assert len(recorder.calls) == 1


async def test_response_headers_keep_a_case_insensitive_lookup(
    served: tuple[DaitemClient, Recorder],
) -> None:
    """A job path comes from `Location`, which a server may write in any case."""
    client, recorder = served
    path = f"/topaze/v5/systems/{SID}/logbook"
    recorder.reply("POST", path, web.json_response({}, headers={"Location": "/v5/job"}))
    _, headers = await client._transport.request_full("POST", path)
    assert headers.get("location") == headers.get("LOCATION") == "/v5/job"


async def test_an_answer_that_is_not_an_object_is_an_api_error(
    served: tuple[DaitemClient, Recorder],
) -> None:
    """Rather than a value of the wrong type handed to the caller."""
    client, recorder = served
    recorder.reply("GET", "/topaze/v1/user", web.json_response([1, 2]))
    with pytest.raises(DaitemApiError, match="expected a JSON object, got list"):
        await client.account.get_user()
