"""Command line interface.

Exit codes are part of the compatibility promise, since callers branch on them rather than
parsing text, so each one is covered here. No test touches a real alarm.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from pydaitem import ArmMode, DaitemAuthError, DaitemError, DaitemSessionBusyError
from pydaitem.cli import (
    EXIT_AUTH,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_SESSION_BUSY,
    EXIT_USAGE,
    main,
)
from pydaitem.models import Inventory, Schedule, ScheduleProgram, SystemStatus

ENV = {
    "DAITEM_EMAIL": "account@example.test",
    "DAITEM_PASSWORD": "password",
    "DAITEM_MASTER_CODE": "0000",
}

STATUS = SystemStatus.from_json(
    {"systemState": "on", "groups": [{"id": 1, "active": True}, {"id": 2, "active": False}]}
)

SCHEDULE = Schedule(
    global_activation=True,
    programs=[ScheduleProgram(id=1, day="monday", hour=22, minute=0, command=True, groups=[1])],
    max_program_count=50,
)

INVENTORY = Inventory.from_json(
    {
        "central": {
            "serialNumber": "SN",
            "type": "INTRUSION",
            "hasIO": True,
            "anomalies": {"defaultMediaAlert": True, "mainPowerSupplyAlert": False},
        },
        "genericSensors": {
            "sensors": [
                {
                    "index": 1,
                    "name": "Front door",
                    "serialNumber": "SN-1",
                    "type": "DEFAULT",
                    "group": 1,
                    "anomalies": {"powerSupplyAlert": True},
                }
            ]
        },
        "commands": [],
    }
)


@pytest.fixture(autouse=True)
def _env(monkeypatch, tmp_path):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("DAITEM_SYSTEM_ID", raising=False)
    # Never touch the real user token file.
    monkeypatch.setattr("pydaitem.cli.parser.DEFAULT_TOKEN_FILE", str(tmp_path / "token"))


@pytest.fixture
def system() -> AsyncMock:
    """A DaitemSystem double, injected in place of the connect() context manager."""
    fake = AsyncMock()
    fake.system_id = 123456
    fake.read_status.return_value = STATUS
    fake.read_inventory.return_value = INVENTORY
    fake.commands.arm.return_value = STATUS
    fake.commands.disarm.return_value = SystemStatus.from_json({"systemState": "off", "groups": []})
    fake.capabilities.list_presets.return_value = [
        {"id": 0, "name": "partial_arming_name_presence"},
        {"id": 1, "name": "partial_arming_name_2"},
    ]
    fake.schedule.read.return_value = SCHEDULE
    fake.schedule.update_program.return_value = ScheduleProgram(
        id=1, day="tuesday", hour=7, minute=30, command=False, groups=[1, 2]
    )
    fake.schedule.delete_program.return_value = None
    fake.schedule.set_active.return_value = None

    class _Ctx:
        async def __aenter__(self):
            return fake

        async def __aexit__(self, *exc):
            return False

    with patch("pydaitem.cli.app.connect", return_value=_Ctx()):
        yield fake


def run(*argv: str, tmp_path=None) -> int:
    args = list(argv)
    if tmp_path is not None:
        args = ["--token-file", str(tmp_path / "token"), *args]
    return main(args)


# -- Reads --------------------------------------------------------------------


def test_status_json_uses_semantic_vocabulary(system, capsys, tmp_path) -> None:
    assert run("--json", "status", tmp_path=tmp_path) == EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["panel_state"] == "armed_full"
    assert payload["armed"] is True
    assert payload["active_groups"] == [1]
    # The raw API vocabulary must never leak into scriptable output.
    assert "on" not in payload.values()


def test_status_human_output(system, capsys, tmp_path) -> None:
    assert run("status", tmp_path=tmp_path) == EXIT_OK
    out = capsys.readouterr().out
    assert "armed_full" in out


def test_devices_reports_faults(system, capsys, tmp_path) -> None:
    assert run("--json", "devices", tmp_path=tmp_path) == EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["panel"]["faults"] == ["transmission_media"]
    assert payload["panel"]["has_io_board"] is True
    assert payload["devices"][0]["faults"] == ["battery"]


def test_presets_shows_the_raw_names(system, capsys, tmp_path) -> None:
    """Raw names, unfiltered by the semantic ArmMode vocabulary: this is the whole point."""
    assert run("--json", "presets", tmp_path=tmp_path) == EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["presets"] == [
        {"id": 0, "name": "partial_arming_name_presence"},
        {"id": 1, "name": "partial_arming_name_2"},
    ]


def test_presets_with_none_defined(system, capsys, tmp_path) -> None:
    system.capabilities.list_presets.return_value = []
    assert run("presets", tmp_path=tmp_path) == EXIT_OK
    assert "No preset defined." in capsys.readouterr().out


def test_schedule_list_shows_programs(system, capsys, tmp_path) -> None:
    assert run("--json", "schedule", "list", tmp_path=tmp_path) == EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["global_activation"] is True
    assert payload["max_program_count"] == 50
    assert payload["programs"] == [
        {"id": 1, "day": "monday", "hour": 22, "minute": 0, "command": "arm", "groups": [1]}
    ]


# -- Schedule -------------------------------------------------------------------


def test_schedule_set_merges_into_the_existing_program(system, tmp_path) -> None:
    """Only the given fields change; the rest comes from the existing program."""
    assert run("--yes", "schedule", "set", "1", "--hour", "23", tmp_path=tmp_path) == EXIT_OK

    sent = system.schedule.update_program.await_args.args[0]
    assert sent.id == 1
    assert sent.hour == 23
    assert sent.day == "monday"
    assert sent.command is True
    assert sent.groups == [1]


def test_schedule_set_can_flip_arm_to_disarm(system, tmp_path) -> None:
    assert run("--yes", "schedule", "set", "1", "--disarm", tmp_path=tmp_path) == EXIT_OK

    sent = system.schedule.update_program.await_args.args[0]
    assert sent.command is False


def test_schedule_set_unknown_id_is_an_error(system, capsys, tmp_path) -> None:
    """Creating a new program is not supported: an unknown id must not silently create one."""
    assert run("--yes", "schedule", "set", "99", "--hour", "1", tmp_path=tmp_path) == EXIT_ERROR
    assert "99" in capsys.readouterr().err
    system.schedule.update_program.assert_not_awaited()


def test_schedule_set_without_confirmation_is_refused(system, tmp_path) -> None:
    with patch("sys.stdin.isatty", return_value=False):
        assert run("schedule", "set", "1", "--hour", "23", tmp_path=tmp_path) == EXIT_USAGE
    system.schedule.update_program.assert_not_awaited()


def test_schedule_delete_requires_confirmation(system, tmp_path) -> None:
    with patch("sys.stdin.isatty", return_value=False):
        assert run("schedule", "delete", "1", tmp_path=tmp_path) == EXIT_USAGE
    system.schedule.delete_program.assert_not_awaited()

    assert run("--yes", "schedule", "delete", "1", tmp_path=tmp_path) == EXIT_OK
    system.schedule.delete_program.assert_awaited_once_with(1)


def test_schedule_activate_and_deactivate(system, tmp_path) -> None:
    assert run("--yes", "schedule", "activate", tmp_path=tmp_path) == EXIT_OK
    system.schedule.set_active.assert_awaited_once_with(True)

    system.schedule.set_active.reset_mock()
    assert run("--yes", "schedule", "deactivate", tmp_path=tmp_path) == EXIT_OK
    system.schedule.set_active.assert_awaited_once_with(False)


# -- Guardrails ---------------------------------------------------------------


def test_arming_without_tty_and_without_yes_is_refused(system, capsys, tmp_path) -> None:
    """A scheduled job must state its intent; silence must never arm a house."""
    with patch("sys.stdin.isatty", return_value=False):
        assert run("arm", tmp_path=tmp_path) == EXIT_USAGE

    assert "--yes" in capsys.readouterr().err
    system.commands.arm.assert_not_awaited()


def test_yes_allows_unattended_arming(system, tmp_path) -> None:
    with patch("sys.stdin.isatty", return_value=False):
        assert run("--yes", "arm", "--mode", "presence", tmp_path=tmp_path) == EXIT_OK

    system.commands.arm.assert_awaited_once_with(ArmMode.PRESENCE)


def test_declining_the_prompt_does_nothing(system, tmp_path) -> None:
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="n"):
        assert run("disarm", tmp_path=tmp_path) == EXIT_USAGE
    system.commands.disarm.assert_not_awaited()


def test_accepting_the_prompt_disarms(system, tmp_path) -> None:
    with patch("sys.stdin.isatty", return_value=True), patch("builtins.input", return_value="y"):
        assert run("disarm", tmp_path=tmp_path) == EXIT_OK
    system.commands.disarm.assert_awaited_once()


# -- Exit codes ---------------------------------------------------------------


def test_session_busy_has_its_own_exit_code(system, tmp_path) -> None:
    """Not a failure: the mobile app is open. A caller should retry, not alert."""
    system.read_status.side_effect = DaitemSessionBusyError("owner")
    assert run("status", tmp_path=tmp_path) == EXIT_SESSION_BUSY


def test_auth_failure_exit_code(system, tmp_path) -> None:
    system.read_status.side_effect = DaitemAuthError("bad credentials")
    assert run("status", tmp_path=tmp_path) == EXIT_AUTH


def test_generic_error_exit_code(system, tmp_path) -> None:
    system.read_status.side_effect = DaitemError("boom")
    assert run("status", tmp_path=tmp_path) == EXIT_ERROR


def test_missing_credentials_is_a_usage_error(monkeypatch, capsys, tmp_path) -> None:
    for key in ENV:
        monkeypatch.delenv(key, raising=False)
    assert run("status", tmp_path=tmp_path) == EXIT_USAGE
    assert "DAITEM_EMAIL" in capsys.readouterr().err


def test_unknown_command_is_rejected(tmp_path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        run("nonsense", tmp_path=tmp_path)
    assert excinfo.value.code == 2
