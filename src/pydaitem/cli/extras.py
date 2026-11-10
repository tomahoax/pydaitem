"""Automations, cameras, clips, the event log, and the raw dump for diagnostics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .._files import write_private
from ..system import DaitemSystem
from ..system.automation import check_position
from .exit_codes import EXIT_ERROR, EXIT_OK, EXIT_USAGE
from .output import _confirm, _emit


async def _cmd_automations(args: argparse.Namespace, system: DaitemSystem) -> int:
    automatisms = await system.automation.read()
    payload = {
        "automations": [
            {
                "id": a.id,
                "label": a.label,
                "category": a.category,
                "commands": a.available_commands,
                "state": a.state,
                "position": a.position,
            }
            for a in automatisms
        ]
    }
    lines = [
        f"{a.id}\t{a.category:<8} {a.label or '-':<24} {a.state or '-'}"
        f"{f' {a.position}' if a.position is not None else ''}\t{','.join(a.available_commands)}"
        for a in automatisms
    ] or ["No automation."]
    _emit(payload, lines, args.json)
    return EXIT_OK


async def _cmd_automate(args: argparse.Namespace, system: DaitemSystem) -> int:
    # Before any call: a mismatch is the caller's mistake, whatever the automation is.
    check_position(args.automation_command, args.position)
    automatisms = {a.id: a for a in await system.automation.read()}
    automatism = automatisms.get(args.id)
    if automatism is None:
        print(f"No automation with id {args.id}. Run `pydaitem automations`.", file=sys.stderr)
        return EXIT_USAGE
    name = automatism.label or automatism.id
    if not _confirm(f"Really send {args.automation_command} to {name}?", args.yes):
        return EXIT_USAGE
    await system.automation.command(automatism, args.automation_command, position=args.position)
    _emit(
        {"id": automatism.id, "sent": args.automation_command},
        [f"Sent {args.automation_command} to {name}."],
        args.json,
    )
    return EXIT_OK


async def _cmd_scenarios(args: argparse.Namespace, system: DaitemSystem) -> int:
    scenarios = await system.scenarios.read()
    payload = {
        "scenarios": [
            {"id": s.id, "name": s.name, "active": s.active, "trigger": s.trigger}
            for s in scenarios
        ]
    }
    lines = [
        f"{s.id}\t{s.name or '-':<24} {s.trigger or '-':<15} {'active' if s.active else 'inactive'}"
        for s in scenarios
    ]
    _emit(payload, lines or ["No scenario."], args.json)
    return EXIT_OK


async def _cmd_scenario(args: argparse.Namespace, system: DaitemSystem) -> int:
    """`scenario run ID`, the only action so far."""
    scenarios = {s.id: s for s in await system.scenarios.read()}
    scenario = scenarios.get(args.id)
    if scenario is None:
        print(f"No scenario with id {args.id}. Run `pydaitem scenarios`.", file=sys.stderr)
        return EXIT_USAGE
    name = scenario.name or str(scenario.id)
    if not _confirm(f"Really run scenario {name}? It may disarm the alarm.", args.yes):
        return EXIT_USAGE
    status = await system.scenarios.run(scenario)
    _emit(
        {
            "id": scenario.id,
            "panel_state": status.panel_state.value,
            "active_groups": status.active_groups,
        },
        [f"Ran {name}. State: {status.panel_state.value}"],
        args.json,
    )
    return EXIT_OK


async def _cmd_cameras(args: argparse.Namespace, system: DaitemSystem) -> int:
    cameras = await system.video.cameras()
    payload = {
        "cameras": [
            {"id": c.id, "name": c.name, "type": c.type, "model": c.model, "status": c.status}
            for c in cameras
        ]
    }
    lines = [f"{c.id}\t{c.type:<12} {c.name or '-':<24} {c.status or '-'}" for c in cameras]
    _emit(payload, lines or ["No camera."], args.json)
    return EXIT_OK


async def _cmd_clips(args: argparse.Namespace, system: DaitemSystem) -> int:
    clips = await system.video.clips()
    payload = {
        "clips": [
            {
                "id": c.id,
                "taken_at": c.taken_at.isoformat() if c.taken_at else None,
                "kind": c.kind,
                "category": c.category,
                "device_uid": c.device_uid,
                "duration_ms": c.duration_ms,
            }
            for c in clips
        ]
    }
    lines = [
        f"{c.taken_at.isoformat() if c.taken_at else '-':<26} {c.kind or '-':<9} "
        f"{c.category or '-':<9} {c.id}"
        for c in clips
    ]
    _emit(payload, lines or ["No clip."], args.json)
    return EXIT_OK


async def _cmd_logbook(args: argparse.Namespace, system: DaitemSystem) -> int:
    entries = (await system.logbook.read())[: args.limit]
    payload = {
        "entries": [{"date": e.date, "title": e.title, "details": e.details} for e in entries]
    }
    _emit(payload, [f"{e.date}\t{e.title}" for e in entries] or ["No event."], args.json)
    return EXIT_OK


async def _cmd_dump(args: argparse.Namespace, system: DaitemSystem) -> int:
    """Write the raw answer of every read to a file, for whoever adds support for it."""
    dump: dict[str, Any] = await system.collect_raw(
        logbook_entries=args.logbook, redact=args.redact
    )
    output = Path(args.output).expanduser()
    # Personal data: readable by its owner only, like the token file.
    try:
        write_private(output, json.dumps(dump, indent=2, ensure_ascii=False, sort_keys=True))
    except OSError as err:
        print(f"Could not write {output}: {err}", file=sys.stderr)
        return EXIT_ERROR
    failed = sorted(dump["errors"])
    _emit(
        {
            "output": str(output),
            "read": sorted(dump["payloads"]),
            "failed": failed,
            "redacted": args.redact,
        },
        [
            f"Wrote {output}.",
            f"Read: {', '.join(sorted(dump['payloads'])) or 'nothing'}.",
            f"Failed: {', '.join(failed) or 'none'}.",
            "Secrets are removed and identifiers shortened. Read it before sharing all the same."
            if args.redact
            else "It holds personal data (names, serial numbers, e-mail addresses): do not "
            "share it.",
        ],
        args.json,
    )
    return EXIT_OK if dump["payloads"] else EXIT_ERROR
