"""Argparse construction for the CLI: the subcommand tree and its input validators."""

from __future__ import annotations

import argparse
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pydaitem",
        description="Read and control a Daitem alarm from the command line.",
        epilog=(
            "Exit codes: 0 success, 1 error, 2 usage, 3 panel session held by another "
            "device, 4 authentication failure."
        ),
    )
    parser.add_argument("--env-file", type=Path, help="KEY=VALUE file holding credentials")
    parser.add_argument(
        "--token-file",
        type=Path,
        default=Path(DEFAULT_TOKEN_FILE),
        help="where to cache the refresh token so runs reuse a session "
        f"(default: {DEFAULT_TOKEN_FILE})",
    )
    parser.add_argument("--system-id", type=int, help="installation to use")
    parser.add_argument("--json", action="store_true", help="machine readable output")
    parser.add_argument("-y", "--yes", action="store_true", help="skip the confirmation")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("systems", help="list the installations this account can reach")
    sub.add_parser("status", help="panel state and active groups")
    sub.add_parser("devices", help="device inventory and active faults")
    sub.add_parser(
        "presets",
        help="raw partial-arming presets (id and name), to see an installation's own wording",
    )
    arm = sub.add_parser("arm", help="arm the alarm (drives a real alarm)")
    arm.add_argument("--mode", choices=sorted(_ARM_MODES), default=ArmMode.AWAY.value)
    sub.add_parser("disarm", help="disarm the alarm (drives a real alarm)")

    schedule = sub.add_parser("schedule", help="recurring arm/disarm programs")
    schedule_sub = schedule.add_subparsers(dest="schedule_action", required=True)
    schedule_sub.add_parser("list", help="show the schedule and its programs")

    schedule_set = schedule_sub.add_parser(
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

    schedule_delete = schedule_sub.add_parser(
        "delete", help="delete a program (drives a real alarm)"
    )
    schedule_delete.add_argument("id", type=int)

    schedule_sub.add_parser("activate", help="enable the whole schedule (drives a real alarm)")
    schedule_sub.add_parser("deactivate", help="disable the whole schedule (drives a real alarm)")

    return parser
