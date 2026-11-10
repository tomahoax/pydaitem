"""The stable surface, frozen: a change here is a breaking change, see docs/python.md.

Each set below is written out in full on purpose. A test that derived it from the code
would pass whatever the code became. Adding a name is allowed in a minor release (update
the set), removing or renaming one is a breaking change (update the changelog too).
"""

from __future__ import annotations

import pickle
import re
from pathlib import Path

import pydaitem
from pydaitem import DaitemClient, DaitemSessionBusyError, DaitemSystem
from pydaitem.cli import exit_codes

TOP_LEVEL = {
    "ARMED_PANEL_STATES",
    "Anomalies",
    "ArmMode",
    "Automatism",
    "AutomatismCategory",
    "AutomatismCommand",
    "AutomatismStateType",
    "Camera",
    "CameraType",
    "Clip",
    "ClipCategory",
    "ClipFormat",
    "ClipKind",
    "CommandStatus",
    "Credentials",
    "DaitemApiError",
    "DaitemAuthError",
    "DaitemBadCodeError",
    "DaitemClient",
    "DaitemCommandError",
    "DaitemConnectionError",
    "DaitemError",
    "DaitemForbiddenError",
    "DaitemNoSessionError",
    "DaitemRateLimitedError",
    "DaitemSessionBusyError",
    "DaitemSessionRestrictedError",
    "DaitemSystem",
    "DaitemTransmitterOfflineError",
    "DaitemUsageError",
    "Device",
    "DeviceKind",
    "Extras",
    "Fault",
    "FileTokenStore",
    "Firmware",
    "Group",
    "Inventory",
    "LogEntry",
    "MemoryTokenStore",
    "MissingCredentials",
    "PanelState",
    "Remedy",
    "Scenario",
    "Schedule",
    "ScheduleProgram",
    "ServerMessage",
    "Snapshot",
    "System",
    "SystemStatus",
    "TokenStore",
    "VERSION",
    "__version__",
    "connect",
    "redact",
    "redact_identifier",
    "resolve_credentials",
}

FACADE = {
    "panel": {"check_code", "read", "transmitter_online", "wait_settled"},
    "inventory": {"read"},
    "capabilities": {"arm_modes", "discovered", "presets"},
    "commands": {"arm", "arm_away", "arm_groups", "arm_presence", "disarm"},
    "schedule": {"delete_program", "read", "set_active", "update_program"},
    "automation": {"command", "read"},
    "scenarios": {"read", "run"},
    "video": {"cameras", "clips"},
    "logbook": {"read"},
}


def _public(obj: object) -> set[str]:
    return {name for name in dir(obj) if not name.startswith("_")}


def test_the_top_level_exports_are_frozen() -> None:
    assert set(pydaitem.__all__) == TOP_LEVEL
    for name in TOP_LEVEL:
        assert hasattr(pydaitem, name), name


def test_the_facade_namespaces_and_methods_are_frozen() -> None:
    system = DaitemSystem(DaitemClient("a@example.test", "p"), 1, "0000")
    assert _public(system) == {
        *FACADE,
        "client",
        "collect_raw",
        "read_extras",
        "read_snapshot",
        "system_id",
    }
    for namespace, methods in FACADE.items():
        assert _public(getattr(system, namespace)) == methods, namespace


def test_the_exit_codes_are_frozen() -> None:
    assert (
        exit_codes.EXIT_OK,
        exit_codes.EXIT_ERROR,
        exit_codes.EXIT_USAGE,
        exit_codes.EXIT_SESSION_BUSY,
        exit_codes.EXIT_AUTH,
        exit_codes.EXIT_INTERRUPTED,
    ) == (0, 1, 2, 3, 4, 130)


def test_every_exception_derives_from_daitem_error() -> None:
    errors = [
        getattr(pydaitem, n) for n in TOP_LEVEL if n.endswith("Error") or n == "MissingCredentials"
    ]
    assert all(issubclass(e, pydaitem.DaitemError) for e in errors)
    assert issubclass(pydaitem.DaitemUsageError, ValueError)


#: Each exception's `code` and default `remedy`. Codes never change once published: a
#: consumer keys translated messages on them.
ERRORS = {
    "DaitemError": ("error", "retry_later"),
    "MissingCredentials": ("missing_credentials", "ask_credentials"),
    "DaitemUsageError": ("usage", "fix_call"),
    "DaitemAuthError": ("auth", "ask_credentials"),
    "DaitemConnectionError": ("connection", "retry_later"),
    "DaitemApiError": ("api", "retry_later"),
    "DaitemForbiddenError": ("forbidden", "not_permitted"),
    "DaitemSessionRestrictedError": ("session_restricted", "not_permitted"),
    "DaitemSessionBusyError": ("session_busy", "retry_later"),
    "DaitemNoSessionError": ("no_session", "retry_later"),
    "DaitemBadCodeError": ("bad_code", "ask_code"),
    "DaitemTransmitterOfflineError": ("transmitter_offline", "unavailable"),
    "DaitemRateLimitedError": ("rate_limited", "retry_later"),
    "DaitemCommandError": ("command", "check_state"),
}

REMEDIES = {
    "retry_later",
    "ask_credentials",
    "ask_code",
    "not_permitted",
    "unavailable",
    "check_state",
    "fix_call",
}


def test_every_exception_has_a_frozen_code_and_remedy() -> None:
    exported = {n for n in TOP_LEVEL if n.endswith("Error") or n == "MissingCredentials"}
    assert exported == set(ERRORS)
    for name, (code, remedy) in ERRORS.items():
        error = getattr(pydaitem, name)()
        assert (error.code, error.remedy) == (code, remedy), name
        assert all(isinstance(v, str) for v in error.placeholders.values()), name


def test_the_remedies_are_frozen() -> None:
    assert {member.value for member in pydaitem.Remedy} == REMEDIES


def test_the_python_guide_gives_each_exception_its_code_and_remedy() -> None:
    """The errors table of docs/python.md, read back against the code it describes."""
    guide = (Path(__file__).resolve().parent.parent / "docs" / "python.md").read_text()
    section = guide.split("## Errors\n", 1)[1].split("\n## ", 1)[0]
    rows = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`") and cells[1].startswith("`"):
            rows[cells[0].strip("`")] = (cells[1].strip("`"), re.findall(r"`(\w+)`", cells[2]))
    assert set(rows) == set(ERRORS) - {"DaitemError"}
    for name, (code, remedies) in rows.items():
        error = getattr(pydaitem, name)()
        assert code == error.code, name
        # The first remedy named is the class's own, any other a refinement the class makes.
        assert remedies[0] == error.remedy.name, name
        assert all(r in pydaitem.Remedy.__members__ for r in remedies), name
    named = re.findall(r"^\| `(\w+)` \| [^`|]", section, flags=re.MULTILINE)
    # The remedy table: one row per member, under its `Remedy` header.
    assert set(named) - {"Remedy"} == set(pydaitem.Remedy.__members__)


def test_a_refined_remedy_survives_pickling() -> None:
    err = pydaitem.DaitemConnectionError("lost", remedy=pydaitem.Remedy.CHECK_STATE)
    assert pickle.loads(pickle.dumps(err)).remedy is pydaitem.Remedy.CHECK_STATE
    command = pydaitem.DaitemCommandError("no", command_status="ERROR CMD FORBIDDEN")
    copy = pickle.loads(pickle.dumps(command))
    assert (copy.remedy, copy.command_status) == (
        pydaitem.Remedy.NOT_PERMITTED,
        "ERROR CMD FORBIDDEN",
    )


def test_a_busy_error_survives_pickling() -> None:
    err = DaitemSessionBusyError("phone", status=409)
    copy = pickle.loads(pickle.dumps(err))
    assert str(copy) == str(err) and copy.holder == "phone" and copy.status == 409


def test_models_take_keyword_arguments_only() -> None:
    try:
        pydaitem.Group(1, True)  # type: ignore[misc]
    except TypeError:
        return
    raise AssertionError("models must refuse positional arguments")


def test_raw_payloads_stay_out_of_repr() -> None:
    group = pydaitem.Group.from_json({"id": 1, "active": True, "serialNumber": "SN-SECRET"})
    assert "SN-SECRET" not in repr(group)
    inventory = pydaitem.Inventory.from_json({"central": {"serialNumber": "x"}, "secret": "s"})
    assert "secret" not in repr(inventory)
