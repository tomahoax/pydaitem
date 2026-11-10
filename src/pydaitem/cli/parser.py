"""Argparse construction for the CLI: the subcommand tree and its input validators."""

from __future__ import annotations

import argparse
import functools
from collections.abc import Callable
from pathlib import Path

from ..const import ArmMode

DEFAULT_TOKEN_FILE = "~/.daitem.token"

_ARM_MODES = {mode.value: mode for mode in ArmMode}
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _bounded_int(low: int, high: int, name: str) -> Callable[[str], int]:
    def validator(value: str) -> int:
        try:
            number = int(value)
        except ValueError as err:
            raise argparse.ArgumentTypeError(f"{name} must be an integer") from err
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"{name} must be between {low} and {high}")
        return number

    return validator


def _group_list(value: str) -> list[int]:
    try:
        return [int(group) for group in value.split(",") if group]
    except ValueError as err:
        raise argparse.ArgumentTypeError(f"invalid group list: {value!r}") from err


def _add_global_options(parser: argparse.ArgumentParser, *, defaults: bool) -> None:
    """Options every command accepts, before or after its name."""

    def default(value: object) -> object:
        return value if defaults else argparse.SUPPRESS

    parser.add_argument(
        "--env-file",
        type=Path,
        default=default(None),
        help="KEY=VALUE file holding credentials",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=default(Path(DEFAULT_TOKEN_FILE)),
        help="where to cache the refresh token so runs reuse a session "
        f"(default: {DEFAULT_TOKEN_FILE})",
    )
    parser.add_argument("--system-id", type=int, default=default(None), help="installation to use")
    parser.add_argument(
        "--json", action="store_true", default=default(False), help="machine readable output"
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", default=default(False), help="skip the confirmation"
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", default=default(False), help="debug logging"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pydaitem",
        description="Read and control a Daitem alarm from the command line.",
        epilog=(
            "Exit codes: 0 success, 1 error, 2 usage, 3 panel session held by another "
            "device, 4 authentication failure."
        ),
    )
    _add_global_options(parser, defaults=True)
    # The same options again on every subcommand, so they also work after it
    # (`pydaitem status --json`). There they default to nothing, leaving the value given
    # before the subcommand, if any, in place.
    shared = argparse.ArgumentParser(add_help=False)
    _add_global_options(shared, defaults=False)

    sub = parser.add_subparsers(dest="command", required=True)
    command = functools.partial(sub.add_parser, parents=[shared])
    command("systems", help="list the installations this account can reach")
    command("logout", help="revoke the stored sign-in and delete the token file")
    command("status", help="panel state, active groups and transmitter connectivity")
    command("devices", help="device inventory and active faults")
    command(
        "presets",
        help="raw partial-arming presets (id and name), to see an installation's own wording",
    )
    command("modes", help="arming modes this installation supports, for `arm --mode`")
    arm = command("arm", help="arm the alarm (drives a real alarm)")
    what = arm.add_mutually_exclusive_group()
    what.add_argument("--mode", choices=sorted(_ARM_MODES), default=ArmMode.AWAY.value)
    what.add_argument(
        "--groups", type=_group_list, help="arm these groups, comma-separated, e.g. 1,2"
    )
    arm.add_argument(
        "--wait",
        type=_bounded_int(1, 600, "--wait"),
        nargs="?",
        const=120,
        metavar="SECONDS",
        help="then wait for the exit delay to end (120 s at most by default)",
    )
    disarm = command("disarm", help="disarm the alarm (drives a real alarm)")
    disarm.add_argument("--groups", type=_group_list, help="disarm these groups, comma-separated")

    command("automations", help="gates, garage doors, shutters, lights and plugs")
    automate = command(
        "automate",
        help="send a command to an automation (drives real equipment)",
    )
    automate.add_argument("id", help="automation id, from `automations`")
    automate.add_argument(
        "automation_command",
        metavar="command",
        type=str.upper,
        help="one of the commands `automations` lists for it",
    )
    automate.add_argument(
        "--position", type=_bounded_int(0, 100, "position"), help="for the POSITION command"
    )
    command("scenarios", help="scenarios defined on the installation")
    scenario = command("scenario", help="run a scenario (drives a real alarm)")
    scenario_sub = scenario.add_subparsers(dest="scenario_action", required=True)
    scenario_command = functools.partial(scenario_sub.add_parser, parents=[shared])
    scenario_run = scenario_command("run", help="run a scenario: it may disarm the alarm")
    scenario_run.add_argument("id", type=int, help="scenario id, from `scenarios`")
    command("cameras", help="cameras and their status (no live video)")
    command("clips", help="recorded clips, on alarm and on demand")
    logbook = command("logbook", help="event log (owner accounts only, slow)")
    logbook.add_argument("--limit", type=_bounded_int(1, 10_000, "limit"), default=50)
    dump = command(
        "dump",
        help="write the raw answer of every read to a file, to report what is missing",
    )
    dump.add_argument("--output", default="daitem-dump.json", help="file to write")
    dump.add_argument(
        "--logbook",
        type=_bounded_int(0, 100, "logbook"),
        default=5,
        help="event log entries to include (0 skips the event log)",
    )
    dump.add_argument(
        "--no-redact",
        dest="redact",
        action="store_false",
        help="keep secrets and personal data as sent, for a file that stays with you",
    )

    schedule = command("schedule", help="recurring arm/disarm programs")
    schedule_sub = schedule.add_subparsers(dest="schedule_action", required=True)
    schedule_command = functools.partial(schedule_sub.add_parser, parents=[shared])
    schedule_command("list", help="show the schedule and its programs")

    schedule_set = schedule_command(
        "set",
        help="update an existing program's day, time, action or groups (drives a real alarm)",
    )
    schedule_set.add_argument(
        "id", type=int, help="existing program id (creating a new one is not supported)"
    )
    schedule_set.add_argument("--day", choices=_DAYS)
    schedule_set.add_argument("--hour", type=_bounded_int(0, 23, "--hour"))
    schedule_set.add_argument("--minute", type=_bounded_int(0, 59, "--minute"))
    arm_or_disarm = schedule_set.add_mutually_exclusive_group()
    arm_or_disarm.add_argument("--arm", action="store_true", help="the program arms at that time")
    arm_or_disarm.add_argument(
        "--disarm", action="store_true", help="the program disarms at that time"
    )
    schedule_set.add_argument(
        "--groups", type=_group_list, help="comma-separated group ids, e.g. 1,2"
    )

    schedule_delete = schedule_command("delete", help="delete a program (drives a real alarm)")
    schedule_delete.add_argument("id", type=int)

    schedule_command("activate", help="enable the whole schedule (drives a real alarm)")
    schedule_command("deactivate", help="disable the whole schedule (drives a real alarm)")

    return parser
