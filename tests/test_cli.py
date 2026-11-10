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
    build_parser,
    main,
)
from pydaitem.models import (
    Automatism,
    Camera,
    Clip,
    Inventory,
    LogEntry,
    Scenario,
    Schedule,
    ScheduleProgram,
    SystemStatus,
)

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
            ],
            "fireTriggers": [{"name": "Kitchen", "isTriggered": True, "anomalies": {}}],
        },
        "commands": [],
        "sirens": [{"name": "Siren", "anomalies": {"autoprotectionMechanicalAlert": True}}],
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
    fake.panel.read.return_value = STATUS
    fake.panel.transmitter_online.return_value = True
    fake.panel.wait_settled.return_value = STATUS
    fake.commands.arm_groups.return_value = STATUS
    fake.capabilities.arm_modes.return_value = frozenset({ArmMode.AWAY, ArmMode.PRESENCE})
    fake.capabilities.discovered = True
    fake.scenarios.read.return_value = [
        Scenario.from_json({"id": 4, "name": "Night", "active": True, "triggerType": "MANUAL"})
    ]
    fake.scenarios.run.return_value = STATUS
    fake.inventory.read.return_value = INVENTORY
    fake.commands.arm.return_value = STATUS
    fake.commands.disarm.return_value = SystemStatus.from_json({"systemState": "off", "groups": []})
    fake.capabilities.presets.return_value = [
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
    siren, fire = payload["devices"][1:]
    assert siren["kind"] == "siren" and siren["faults"] == ["tamper_mechanical"]
    assert fire["kind"] == "fire_trigger" and fire["triggered"] is True


def test_devices_text_flags_a_triggered_device(system, capsys, tmp_path) -> None:
    assert run("devices", tmp_path=tmp_path) == EXIT_OK
    line = next(x for x in capsys.readouterr().out.splitlines() if "Kitchen" in x)
    assert line.startswith("fire_trigger") and line.endswith("TRIGGERED")


def test_presets_shows_the_raw_names(system, capsys, tmp_path) -> None:
    """Raw names, unfiltered by the semantic ArmMode vocabulary: this is the whole point."""
    assert run("--json", "presets", tmp_path=tmp_path) == EXIT_OK

    payload = json.loads(capsys.readouterr().out)
    assert payload["presets"] == [
        {"id": 0, "name": "partial_arming_name_presence"},
        {"id": 1, "name": "partial_arming_name_2"},
    ]


def test_presets_with_none_defined(system, capsys, tmp_path) -> None:
    system.capabilities.presets.return_value = []
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


def test_schedule_set_unknown_id_is_a_usage_error(system, capsys, tmp_path) -> None:
    """Creating a new program is not supported: an unknown id must not silently create one."""
    assert run("--yes", "schedule", "set", "99", "--hour", "1", tmp_path=tmp_path) == EXIT_USAGE
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
    system.panel.read.side_effect = DaitemSessionBusyError("owner")
    assert run("status", tmp_path=tmp_path) == EXIT_SESSION_BUSY


def test_auth_failure_exit_code(system, tmp_path) -> None:
    system.panel.read.side_effect = DaitemAuthError("bad credentials")
    assert run("status", tmp_path=tmp_path) == EXIT_AUTH


def test_generic_error_exit_code(system, tmp_path) -> None:
    system.panel.read.side_effect = DaitemError("boom")
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


GATE = Automatism.from_json(
    {"id": "gate-1", "label": "Portail", "category": "GATE", "availableCommands": ["PULSE"]}
)


def test_automations_lists_commands_and_state(system, tmp_path, capsys) -> None:
    system.automation.read.return_value = [GATE]
    assert run("--json", "automations", tmp_path=tmp_path) == EXIT_OK
    (automation,) = json.loads(capsys.readouterr().out)["automations"]
    assert automation["id"] == "gate-1" and automation["commands"] == ["PULSE"]


def test_automate_asks_first_and_sends_the_command(system, tmp_path) -> None:
    system.automation.read.return_value = [GATE]
    # Without a terminal and without --yes, nothing is sent.
    assert run("automate", "gate-1", "pulse", tmp_path=tmp_path) == EXIT_USAGE
    system.automation.command.assert_not_called()
    assert run("--yes", "automate", "gate-1", "pulse", tmp_path=tmp_path) == EXIT_OK
    system.automation.command.assert_awaited_once_with(GATE, "PULSE", position=None)


@pytest.mark.parametrize(
    "argv", [["gate-1", "PULSE", "--position", "50"], ["shutter-1", "POSITION"]]
)
def test_automate_position_mismatch_is_a_usage_error(system, tmp_path, argv) -> None:
    assert run("--yes", "automate", *argv, tmp_path=tmp_path) == EXIT_USAGE
    system.automation.read.assert_not_awaited()
    system.automation.command.assert_not_called()


def test_automate_unknown_id_is_a_usage_error(system, tmp_path) -> None:
    system.automation.read.return_value = [GATE]
    assert run("--yes", "automate", "nope", "PULSE", tmp_path=tmp_path) == EXIT_USAGE
    system.automation.command.assert_not_called()


def test_cameras_and_clips(system, tmp_path, capsys) -> None:
    system.video.cameras.return_value = [
        Camera.from_json({"id": 3, "name": "Entrée", "type": "DAHUA"})
    ]
    system.video.clips.return_value = [Clip.from_json({"id": "f1", "timestamp": 1_700_000_000})]
    assert run("--json", "cameras", tmp_path=tmp_path) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["cameras"][0]["name"] == "Entrée"
    assert run("--json", "clips", tmp_path=tmp_path) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["clips"][0]["taken_at"].startswith("2023-11-14")


def test_logbook_is_capped(system, tmp_path, capsys) -> None:
    system.logbook.read.return_value = [
        LogEntry.from_json({"date": f"2026-09-07T15:{i:02d}", "title": "t"}) for i in range(5)
    ]
    assert run("--json", "logbook", "--limit", "2", tmp_path=tmp_path) == EXIT_OK
    assert len(json.loads(capsys.readouterr().out)["entries"]) == 2


def test_dump_writes_the_raw_answers(system, tmp_path, capsys) -> None:
    system.collect_raw.return_value = {
        "system_id": 123456,
        "payloads": {"automatisms": {"automatisms": []}},
        "errors": {"logbook": "DaitemForbiddenError: denied"},
    }
    output = tmp_path / "dump.json"
    assert run("dump", "--output", str(output), "--logbook", "0", tmp_path=tmp_path) == EXIT_OK
    system.collect_raw.assert_awaited_once_with(logbook_entries=0, redact=True)
    assert json.loads(output.read_text())["payloads"] == {"automatisms": {"automatisms": []}}
    assert "Secrets are removed" in capsys.readouterr().out


def test_dump_keeps_personal_data_only_when_asked(system, tmp_path, capsys) -> None:
    system.collect_raw.return_value = {"system_id": 1, "payloads": {}, "errors": {}}
    output = tmp_path / "dump.json"
    argv = ["dump", "--output", str(output), "--logbook", "0", "--no-redact", "--json"]
    run(*argv, tmp_path=tmp_path)
    system.collect_raw.assert_awaited_once_with(logbook_entries=0, redact=False)
    assert json.loads(capsys.readouterr().out)["redacted"] is False


@pytest.mark.parametrize(
    "argv",
    [
        ["status", "--json"],
        ["--json", "status"],
        ["schedule", "list", "--json"],
        ["schedule", "--json", "list"],
    ],
)
def test_global_options_work_before_or_after_the_command(argv: list[str]) -> None:
    """The docs write `pydaitem status --json`: argparse alone would reject it."""
    assert build_parser().parse_args(argv).json is True


def test_an_option_given_before_the_command_is_kept() -> None:
    args = build_parser().parse_args(["--token-file", "/tmp/t", "--yes", "arm", "--mode", "away"])
    assert str(args.token_file) == "/tmp/t" and args.yes is True and args.json is False


# -- Standard actions -------------------------------------------------------------------


def test_status_reports_the_transmitter(system, capsys, tmp_path) -> None:
    assert run("--json", "status", tmp_path=tmp_path) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["transmitter_online"] is True


def test_status_survives_an_unknown_transmitter(system, capsys, tmp_path) -> None:
    """The state was read: a failed connectivity check alone must not fail the command."""
    system.panel.transmitter_online.side_effect = DaitemError("no record")
    assert run("status", tmp_path=tmp_path) == EXIT_OK
    assert "Transmitter : unknown" in capsys.readouterr().out


def test_arm_groups(system, tmp_path) -> None:
    assert run("--yes", "arm", "--groups", "1,3", tmp_path=tmp_path) == EXIT_OK
    system.commands.arm_groups.assert_awaited_once_with({1: True, 3: True})
    system.commands.arm.assert_not_awaited()


def test_disarm_groups(system, tmp_path) -> None:
    assert run("--yes", "disarm", "--groups", "2", tmp_path=tmp_path) == EXIT_OK
    system.commands.arm_groups.assert_awaited_once_with({2: False})
    system.commands.disarm.assert_not_awaited()


@pytest.mark.parametrize("command", ["arm", "disarm"])
@pytest.mark.parametrize("groups", ["", ","])
def test_empty_groups_never_drive_every_group(system, tmp_path, command, groups) -> None:
    assert run("--yes", command, "--groups", groups, tmp_path=tmp_path) == EXIT_USAGE
    system.commands.arm.assert_not_awaited()
    system.commands.disarm.assert_not_awaited()
    system.commands.arm_groups.assert_not_awaited()


def test_mode_and_groups_are_exclusive(system, tmp_path) -> None:
    with pytest.raises(SystemExit) as exited:
        run("--yes", "arm", "--mode", "presence", "--groups", "1", tmp_path=tmp_path)
    assert exited.value.code == EXIT_USAGE


def test_arm_wait_failure_after_the_command_still_exits_ok(system, tmp_path, capsys) -> None:
    """The panel accepted the command: a script must not send it a second time."""
    system.panel.wait_settled.side_effect = DaitemSessionBusyError("phone")
    assert run("--yes", "--json", "arm", "--wait", tmp_path=tmp_path) == EXIT_OK
    captured = capsys.readouterr()
    assert "wait for the exit delay failed" in captured.err
    assert json.loads(captured.out)["panel_state"]


@pytest.mark.parametrize(("argv", "timeout"), [(["--wait"], 120), (["--wait", "30"], 30)])
def test_arm_can_wait_for_the_exit_delay(system, tmp_path, argv, timeout) -> None:
    assert run("--yes", "arm", *argv, tmp_path=tmp_path) == EXIT_OK
    system.panel.wait_settled.assert_awaited_once_with(timeout=timeout)


def test_arm_does_not_wait_unless_asked(system, tmp_path) -> None:
    assert run("--yes", "arm", tmp_path=tmp_path) == EXIT_OK
    system.panel.wait_settled.assert_not_awaited()


def test_modes(system, capsys, tmp_path) -> None:
    assert run("--json", "modes", tmp_path=tmp_path) == EXIT_OK
    assert json.loads(capsys.readouterr().out) == {
        "modes": ["away", "presence"],
        "discovered": True,
    }


def test_scenarios_list(system, capsys, tmp_path) -> None:
    assert run("--json", "scenarios", tmp_path=tmp_path) == EXIT_OK
    assert json.loads(capsys.readouterr().out)["scenarios"] == [
        {"id": 4, "name": "Night", "active": True, "trigger": "MANUAL"}
    ]


def test_scenario_run_asks_then_runs(system, tmp_path) -> None:
    with patch("sys.stdin.isatty", return_value=False):
        assert run("scenario", "run", "4", tmp_path=tmp_path) == EXIT_USAGE
    system.scenarios.run.assert_not_awaited()
    assert run("--yes", "scenario", "run", "4", tmp_path=tmp_path) == EXIT_OK
    (scenario,), _ = system.scenarios.run.await_args
    assert scenario.id == 4


def test_unknown_scenario(system, capsys, tmp_path) -> None:
    assert run("--yes", "scenario", "run", "9", tmp_path=tmp_path) == EXIT_USAGE
    assert "No scenario with id 9" in capsys.readouterr().err


# -- JSON shapes, frozen ---------------------------------------------------------------
# The table of docs/cli.md, written out: fields may be added (update it here), not removed
# or renamed.

_ITEM = {
    "devices": {"name", "kind", "group", "inhibited", "faults", "triggered"},
    "automations": {"id", "label", "category", "commands", "state", "position"},
    "scenarios": {"id", "name", "active", "trigger"},
    "cameras": {"id", "name", "type", "model", "status"},
    "clips": {"id", "taken_at", "kind", "category", "device_uid", "duration_ms"},
    "entries": {"date", "title", "details"},
    "programs": {"id", "day", "hour", "minute", "command", "groups"},
}


@pytest.mark.parametrize(
    ("argv", "keys"),
    [
        (
            ["status"],
            {"system_id", "panel_state", "armed", "arming", "active_groups", "transmitter_online"},
        ),
        (["modes"], {"modes", "discovered"}),
        (["devices"], {"panel", "devices"}),
        (["presets"], {"presets"}),
        (["arm"], {"panel_state", "active_groups"}),
        (["disarm"], {"panel_state", "active_groups"}),
        (["schedule", "list"], {"global_activation", "max_program_count", "programs"}),
        (["schedule", "set", "1", "--hour", "7"], set(_ITEM["programs"])),
        (["schedule", "delete", "1"], {"deleted"}),
        (["schedule", "activate"], {"global_activation"}),
        (["automations"], {"automations"}),
        (["automate", "gate-1", "PULSE"], {"id", "sent"}),
        (["scenarios"], {"scenarios"}),
        (["scenario", "run", "4"], {"id", "panel_state", "active_groups"}),
        (["cameras"], {"cameras"}),
        (["clips"], {"clips"}),
        (["logbook"], {"entries"}),
    ],
)
def test_the_json_shapes_are_frozen(system, capsys, tmp_path, argv, keys) -> None:
    system.automation.read.return_value = [GATE]
    system.video.cameras.return_value = [Camera.from_json({"id": 1, "name": "Garden"})]
    system.video.clips.return_value = [Clip.from_json({"id": "f1"})]
    system.logbook.read.return_value = [LogEntry.from_json({"date": "d", "title": "t"})]
    assert run("--yes", "--json", *argv, tmp_path=tmp_path) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert set(payload) == keys
    for name, item_keys in _ITEM.items():
        for item in payload.get(name) or []:
            assert set(item) == item_keys, name
    if "panel" in payload:
        assert set(payload["panel"]) == {"type", "has_io_board", "faults"}
