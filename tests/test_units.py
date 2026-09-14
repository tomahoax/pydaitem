"""Pure unit tests: no network, no alarm touched."""

from __future__ import annotations

import base64
import hashlib

import pytest

from pydaitem import VERSION, DaitemClient, DaitemError, PanelState, SystemStatus
from pydaitem.client.pkce import _FORM_ACTION_RE, _pkce_pair, _query_param
from pydaitem.client.transport import app_headers
from pydaitem.models import Inventory


def test_pkce_pair_is_rfc7636_compliant() -> None:
    verifier, challenge = _pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert "=" not in challenge


def test_pkce_pair_is_random() -> None:
    assert _pkce_pair()[0] != _pkce_pair()[0]


def test_form_action_extraction() -> None:
    html = (
        '<html><body><form id="kc-form-login" '
        'action="https://auth.example/realms/daitem/login-actions/authenticate'
        '?session_code=abc&amp;execution=xyz" method="post"></form></body></html>'
    )
    match = _FORM_ACTION_RE.search(html)
    assert match is not None
    assert "session_code=abc" in match.group(1).replace("&amp;", "&")


def test_query_param_extracts_authorization_code() -> None:
    location = "daitemsecure://auth?session_state=s&iss=https%3A%2F%2Fx&code=THE-CODE"
    assert _query_param(location, "code") == "THE-CODE"
    assert _query_param(location, "absent") is None


def test_system_status_arming_and_armed() -> None:
    # Consumers read panel_state, the stable vocabulary, never the raw string.
    tempo = SystemStatus.from_json({"systemState": "tempo", "groups": []})
    assert tempo.is_arming
    assert not tempo.is_armed

    armed = SystemStatus.from_json(
        {
            "systemState": "on",
            "groups": [{"id": 1, "active": True}, {"id": 2, "active": False}],
            "commandStatus": "CMD_OK",
        }
    )
    assert armed.is_armed
    assert not armed.is_arming
    assert armed.active_groups == [1]

    off = SystemStatus.from_json({"systemState": "off", "groups": []})
    assert not off.is_armed and not off.is_arming
    assert off.panel_state is PanelState.DISARMED


def test_inventory_parses_devices_and_anomalies() -> None:
    inventory = Inventory.from_json(
        {
            "central": {
                "serialNumber": "SN-CENTRAL",
                "type": "INTRUSION",
                "hasIO": True,
                "anomalies": {"defaultMediaAlert": True, "radioAlert": False},
                "plug": {"serialNumber": "SN-PLUG"},
            },
            "genericSensors": {
                "sensors": [
                    {
                        "index": 1,
                        "name": "Front door",
                        "serialNumber": "SN-1",
                        "type": "DEFAULT",
                        "group": 1,
                        "isInhibited": False,
                        "anomalies": {"powerSupplyAlert": False},
                    }
                ]
            },
            "commands": [{"index": 1, "name": "Remote", "serialNumber": "SN-C1", "type": "REMOTE"}],
        }
    )
    assert inventory.central_serial == "SN-CENTRAL"
    assert inventory.plug_serial == "SN-PLUG"
    assert inventory.has_io is True
    assert inventory.central_anomalies.active == ["defaultMediaAlert"]
    assert len(inventory.sensors) == 1
    assert len(inventory.controls) == 1
    assert inventory.sensors[0].group == 1
    # The API exposes no open/closed state, so the model must not invent one.
    assert not hasattr(inventory.sensors[0], "is_open")


def test_inventory_parses_the_three_firmware_versions() -> None:
    """The panel carries two firmwares, its transmission module a third.

    Shapes taken from a live installation: the central unit reports SOFT and RADIO, the
    plug reports SOFT alone, and only the plug entry carries the optional metadata.
    """
    inventory = Inventory.from_json(
        {
            "central": {
                "firmwareInfo": {
                    "firmwares": [
                        {"firmwareType": "SOFT", "currentVersion": {"releaseVersion": "6.4.13"}},
                        {"firmwareType": "RADIO", "currentVersion": {"releaseVersion": "15"}},
                    ]
                },
                "plug": {
                    "serialNumber": "SN-PLUG",
                    "firmwareInfo": {
                        "firmwares": [
                            {
                                "firmwareType": "SOFT",
                                "currentVersion": {
                                    "releaseVersion": "7.8.4",
                                    "releaseDate": 1746576000000,
                                    "fileName": "image.bin",
                                    "isCritical": False,
                                },
                            }
                        ]
                    },
                },
            }
        }
    )
    assert inventory.software_version == "6.4.13"
    assert inventory.radio_version == "15"
    assert inventory.transmitter_version == "7.8.4"

    plug = inventory.plug_firmwares[0]
    assert plug.release_date == 1746576000000
    assert plug.file_name == "image.bin"
    assert plug.is_critical is False


def test_missing_firmware_information_is_absent_not_empty() -> None:
    """An installation that reports no firmware must yield None, never a blank string."""
    inventory = Inventory.from_json({"central": {"serialNumber": "SN"}})
    assert inventory.central_firmwares == []
    assert inventory.software_version is None
    assert inventory.radio_version is None
    assert inventory.transmitter_version is None


def test_an_unknown_firmware_type_is_kept_rather_than_dropped() -> None:
    """`firmwareType` is a raw string on purpose, so a new value survives parsing."""
    inventory = Inventory.from_json(
        {
            "central": {
                "firmwareInfo": {
                    "firmwares": [
                        {
                            "firmwareType": "SOMETHING_NEW",
                            "currentVersion": {"releaseVersion": "1.0"},
                        },
                        {"firmwareType": "SOFT", "currentVersion": {"releaseVersion": "6.4.13"}},
                    ]
                }
            }
        }
    )
    assert [f.kind for f in inventory.central_firmwares] == ["SOMETHING_NEW", "SOFT"]
    # The known type still resolves, the unknown one does not shadow it.
    assert inventory.software_version == "6.4.13"


def test_headers_identify_the_client_honestly() -> None:
    """The client announces itself as pydaitem rather than impersonating the app.

    Only X-App-Name keeps the app value: the server requires it as a product routing key.
    X-App-Version is required by connect but its value is free, so we send our own.
    """
    headers = app_headers()
    assert headers["X-App-Name"] == "eNova"
    assert headers["X-App-Version"] == VERSION
    assert headers["X-App-Platform"] == "python"

    user_agent = headers["User-Agent"]
    assert user_agent.startswith(f"pydaitem/{VERSION}")
    assert "Python/" in user_agent
    for forbidden in ("Daitem Secure", "Alamofire", "iOS", "com.daitem"):
        assert forbidden not in user_agent


async def test_get_job_rejects_a_path_not_shaped_like_a_logbook_job() -> None:
    """A caller-supplied path must not redirect the authenticated request elsewhere.

    `job_path` normally comes from `create_job`'s own `Location` header, but `get_job`
    accepts it as a plain string: without this check, any string would be sent as-is to
    `api_base`, with the bearer token attached.
    """
    client = DaitemClient("account@example.test", "password")
    try:
        for bad_path in (
            "/topaze/v1/user",
            "/topaze/v5/systems/1/schedule",
            "/topaze/v5/systems/1/logbook/",
            "https://evil.example/topaze/v5/systems/1/logbook/job",
        ):
            with pytest.raises(DaitemError):
                await client.logbook.get_job(bad_path)
    finally:
        await client.close()
