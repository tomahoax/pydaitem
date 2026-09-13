"""Reads (systems, status, devices, presets) and the arm/disarm control command."""

from __future__ import annotations

import argparse
from typing import Any

from ..client import DaitemClient
from ..credentials import Credentials
from ..system import DaitemSystem
from ..tokens import FileTokenStore
from .exit_codes import EXIT_OK, EXIT_USAGE
from .output import _confirm, _emit
from .parser import _ARM_MODES


async def _cmd_systems(args: argparse.Namespace, creds: Credentials, store: FileTokenStore) -> int:
    client = DaitemClient(creds.email, creds.password, token_store=store)
    try:
        systems = await client.account.list_systems()
    finally:
        await client.close()
    payload = {
        "systems": [
            {"id": s.id, "name": s.name, "owner": s.is_owner, "vendor": s.vendor} for s in systems
        ]
    }
    _emit(
        payload,
        [f"{s.id}\t{s.name}\t{'owner' if s.is_owner else 'restricted'}" for s in systems],
        args.json,
    )
    return EXIT_OK


async def _cmd_status(args: argparse.Namespace, system: DaitemSystem) -> int:
    status = await system.read_status()
    payload = {
        "system_id": system.system_id,
        "panel_state": status.panel_state.value,
        "armed": status.is_armed,
        "arming": status.is_arming,
        "active_groups": status.active_groups,
    }
    _emit(
        payload,
        [
            f"State  : {status.panel_state.value}",
            f"Groups : {status.active_groups or 'none active'}",
        ],
        args.json,
    )
    return EXIT_OK


async def _cmd_devices(args: argparse.Namespace, system: DaitemSystem) -> int:
    inventory = await system.read_inventory()
    devices: list[dict[str, Any]] = []
    device_lines: list[str] = []
    for device in inventory.devices:
        faults = sorted(f.value for f in device.anomalies.faults)
        devices.append(
            {
                "name": device.name,
                "kind": device.kind,
                "group": device.group,
                "inhibited": device.inhibited,
                "faults": faults,
            }
        )
        device_lines.append(
            f"{device.kind:<8} {device.name:<28} group={device.group} {', '.join(faults) or '-'}"
        )

    panel_faults = sorted(f.value for f in inventory.central_anomalies.faults)
    payload: dict[str, Any] = {
        "panel": {
            "type": inventory.central_type,
            "has_io_board": inventory.has_io,
            "faults": panel_faults,
        },
        "devices": devices,
    }

    lines = [
        f"Panel  : {inventory.central_type}, I/O board={inventory.has_io}",
        f"Faults : {', '.join(panel_faults) or 'none'}",
        "",
        *device_lines,
    ]
    _emit(payload, lines, args.json)
    return EXIT_OK


async def _cmd_presets(args: argparse.Namespace, system: DaitemSystem) -> int:
    presets = await system.capabilities.list_presets()
    payload: dict[str, Any] = {"presets": presets}
    lines = [f"{item.get('id')}\t{item.get('name')}" for item in presets] or ["No preset defined."]
    _emit(payload, lines, args.json)
    return EXIT_OK


async def _cmd_control(args: argparse.Namespace, system: DaitemSystem) -> int:
    action = "disarm" if args.command == "disarm" else f"arm ({args.mode})"
    if not _confirm(f"Really {action} the alarm?", args.yes):
        return EXIT_USAGE

    if args.command == "disarm":
        status = await system.commands.disarm()
    else:
        status = await system.commands.arm(_ARM_MODES[args.mode])

    _emit(
        {"panel_state": status.panel_state.value, "active_groups": status.active_groups},
        [f"State: {status.panel_state.value}"],
        args.json,
    )
    return EXIT_OK
