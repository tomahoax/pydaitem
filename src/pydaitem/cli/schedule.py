"""Recurring arm/disarm programs: `pydaitem schedule list/set/delete/activate/deactivate`."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ..models import ScheduleProgram
from ..system import DaitemSystem
from .exit_codes import EXIT_ERROR, EXIT_OK, EXIT_USAGE
from .output import _confirm, _emit


def _program_payload(program: ScheduleProgram) -> dict[str, Any]:
    return {
        "id": program.id,
        "day": program.day,
        "hour": program.hour,
        "minute": program.minute,
        "command": "arm" if program.command else "disarm",
        "groups": program.groups,
    }


def _program_line(program: ScheduleProgram) -> str:
    action = "arm" if program.command else "disarm"
    time = f"{program.day} {program.hour:02d}:{program.minute:02d}"
    return f"{program.id}\t{time}\t{action}\tgroups={program.groups}"


async def _cmd_schedule(args: argparse.Namespace, system: DaitemSystem) -> int:
    if args.schedule_action == "list":
        return await _cmd_schedule_list(args, system)
    if args.schedule_action == "set":
        return await _cmd_schedule_set(args, system)
    if args.schedule_action == "delete":
        return await _cmd_schedule_delete(args, system)
    if args.schedule_action in {"activate", "deactivate"}:
        return await _cmd_schedule_activate(args, system)
    return EXIT_USAGE  # pragma: no cover - argparse rejects this first


async def _cmd_schedule_list(args: argparse.Namespace, system: DaitemSystem) -> int:
    schedule = await system.schedule.read()
    payload: dict[str, Any] = {
        "global_activation": schedule.global_activation,
        "max_program_count": schedule.max_program_count,
        "programs": [_program_payload(p) for p in schedule.programs],
    }
    lines = [f"Global activation: {schedule.global_activation}", ""] + (
        [_program_line(p) for p in schedule.programs] or ["No program defined."]
    )
    _emit(payload, lines, args.json)
    return EXIT_OK


async def _cmd_schedule_set(args: argparse.Namespace, system: DaitemSystem) -> int:
    schedule = await system.schedule.read()
    existing = next((p for p in schedule.programs if p.id == args.id), None)
    if existing is None:
        print(
            f"No program with id {args.id}. Creating a new program is not supported "
            "(never confirmed on the live API) - only an existing id can be updated.",
            file=sys.stderr,
        )
        return EXIT_ERROR

    command = existing.command
    if args.arm:
        command = True
    elif args.disarm:
        command = False

    updated = ScheduleProgram(
        id=existing.id,
        day=args.day or existing.day,
        hour=existing.hour if args.hour is None else args.hour,
        minute=existing.minute if args.minute is None else args.minute,
        command=command,
        groups=existing.groups if args.groups is None else args.groups,
    )

    if not _confirm(f"Really update schedule program {args.id}?", args.yes):
        return EXIT_USAGE

    result = await system.schedule.update_program(updated)
    _emit(
        _program_payload(result),
        [f"Program {result.id} updated: {_program_line(result)}"],
        args.json,
    )
    return EXIT_OK


async def _cmd_schedule_delete(args: argparse.Namespace, system: DaitemSystem) -> int:
    if not _confirm(f"Really delete schedule program {args.id}?", args.yes):
        return EXIT_USAGE
    await system.schedule.delete_program(args.id)
    _emit({"deleted": args.id}, [f"Program {args.id} deleted."], args.json)
    return EXIT_OK


async def _cmd_schedule_activate(args: argparse.Namespace, system: DaitemSystem) -> int:
    active = args.schedule_action == "activate"
    verb = "enable" if active else "disable"
    if not _confirm(f"Really {verb} the schedule?", args.yes):
        return EXIT_USAGE
    await system.schedule.set_active(active)
    _emit(
        {"global_activation": active},
        [f"Schedule {'enabled' if active else 'disabled'}."],
        args.json,
    )
    return EXIT_OK
