"""Answers shaped otherwise than expected stay within DaitemError, and ids stay in their path.

The transport is replaced by a stub: what is under test is how the library reacts to an
answer, not the network.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from pydaitem import (
    ArmMode,
    DaitemApiError,
    DaitemClient,
    DaitemSystem,
    DaitemUsageError,
    MissingCredentials,
    PanelState,
    resolve_credentials,
)
from pydaitem.client import jobs
from pydaitem.client.paths import segment
from pydaitem.models import Inventory, Schedule, SystemStatus

SID = 7


def stubbed(**answers: object) -> DaitemClient:
    """A client whose transport answers each method with the given value."""
    client = DaitemClient("a@example.test", "p")
    for name, value in answers.items():
        setattr(client._transport, name, AsyncMock(return_value=value))
    return client


# -- Models --------------------------------------------------------------------------


@pytest.mark.parametrize("answer", [[{"name": "No id"}], [{"id": "abc"}], [{"id": True}]])
async def test_a_system_without_a_usable_id_is_an_api_error(answer: object) -> None:
    client = stubbed(request=answer)
    with pytest.raises(DaitemApiError, match="systems: unexpected answer"):
        await client.account.list_systems()


async def test_a_numeric_string_id_is_read_as_a_number() -> None:
    client = stubbed(request=[{"id": "42", "role": "1"}])
    (system,) = await client.account.list_systems()
    assert system.id == 42 and system.is_owner


async def test_a_state_that_is_not_an_object_is_an_api_error() -> None:
    client = DaitemClient("a@example.test", "p")
    client._transport.request_full = AsyncMock(return_value=(["off"], {}))  # type: ignore[method-assign]
    with pytest.raises(DaitemApiError, match="expected a JSON object"):
        await client.panel.get_state(SID)


def test_odd_state_fields_read_as_unknown_rather_than_crash() -> None:
    status = SystemStatus.from_json({"systemState": ["on"], "groups": 5})
    assert status.panel_state is PanelState.UNKNOWN and status.groups == []


async def test_a_command_answer_that_is_not_an_object_is_an_api_error() -> None:
    client = DaitemClient("a@example.test", "p")
    client._transport.request_full = AsyncMock(return_value=([1], {}))  # type: ignore[method-assign]
    with pytest.raises(DaitemApiError):
        await client.commands.disarm(SID)


def test_inventory_odd_nested_fields_are_tolerated() -> None:
    inventory = Inventory.from_json(
        {
            "central": "?",
            "plug": {"firmwareInfo": ["?"]},
            "genericSensors": {
                "sensors": [
                    {"name": "Door", "anomalies": ["?"], "firmwareInfo": {"firmwares": [1]}}
                ]
            },
        }
    )
    assert inventory.central_type == "" and inventory.transmitter_version is None
    (door,) = inventory.sensors
    assert not door.anomalies and door.firmwares == []


def test_schedule_odd_programs_are_skipped() -> None:
    schedule = Schedule.from_json({"programs": ["?", {"id": 1, "groups": 5}]})
    (program,) = schedule.programs
    assert program.id == 1 and program.groups == []


async def test_presets_without_a_user_id_do_not_stop_arming_away() -> None:
    client = stubbed(request_object={"firstName": "Ann"})
    system = DaitemSystem(client, SID, "0000")
    system._state.session = lambda: _null_session()  # type: ignore[method-assign]
    assert await system.capabilities.arm_modes() == frozenset({ArmMode.AWAY})


class _null_session:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


# -- Path segments -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"), [(12, "12"), ("gate-1", "gate-1"), ("../x", "..%2Fx"), ("a?b", "a%3Fb")]
)
def test_a_segment_stays_one_segment(value: object, expected: str) -> None:
    assert segment(value) == expected


@pytest.mark.parametrize("value", ["", ".", "..", True])
def test_an_unusable_segment_is_refused(value: object) -> None:
    with pytest.raises(DaitemUsageError, match="not a usable path segment"):
        segment(value)


async def test_an_automation_id_cannot_move_the_command() -> None:
    client = stubbed(request_object={})
    await client.automation.command(SID, "../../users/1", "ON")
    path = client._transport.request_object.await_args.args[1]  # type: ignore[attr-defined]
    assert path == f"/topaze/v5/systems/{SID}/automatisms/..%2F..%2Fusers%2F1/command"


_LOGBOOK = re.compile(rf"/topaze/v5/systems/\d+/logbook/{jobs.JOB_ID}")


@pytest.mark.parametrize(
    "location",
    ["/v5/systems/7/logbook/..", "/v5/systems/7/logbook/%2e%2e", "/v5/systems/7/logbook/a?b"],
)
def test_a_job_path_cannot_step_out(location: str) -> None:
    with pytest.raises(DaitemApiError, match="not a logbook job path"):
        jobs.job_path(location, _LOGBOOK, "logbook job")


def test_a_job_path_of_another_installation_is_refused() -> None:
    with pytest.raises(DaitemApiError, match="another installation"):
        jobs.job_path("/v5/systems/8/logbook/j1", _LOGBOOK, "logbook job", system_id=SID)
    assert jobs.job_path("/v5/systems/7/logbook/j-1", _LOGBOOK, "logbook job", system_id=SID)


# -- Credentials ---------------------------------------------------------------------------


def test_a_non_numeric_system_id_is_a_credentials_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DAITEM_SYSTEM_ID", "home")
    with pytest.raises(MissingCredentials, match="must be a number"):
        resolve_credentials(email="a@example.test", password="p", code="1")


def test_an_unreadable_env_file_is_a_credentials_error(tmp_path: Path) -> None:
    with pytest.raises(MissingCredentials, match="Cannot read the env file"):
        resolve_credentials(email="a@example.test", password="p", code="1", env_file=tmp_path)
