"""Reads (systems, status, devices, presets) and the arm/disarm control command."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ..client import DaitemClient
from ..credentials import Credentials
from ..exceptions import DaitemError
from ..system import DaitemSystem
from ..tokens import FileTokenStore
from .exit_codes import EXIT_OK, EXIT_USAGE
from .output import _confirm, _emit
from .parser import _ARM_MODES


async def _cmd_logout(args: argparse.Namespace, creds: Credentials, store: FileTokenStore) -> int:
    async with DaitemClient(creds.email, creds.password, token_store=store) as client:
        await client.logout()
    _emit(
        {"signed_out": True},
        ["Signed out: the stored sign-in is revoked and the token file deleted."],
        args.json,
    )
    return EXIT_OK


async def _cmd_systems(args: argparse.Namespace, creds: Credentials, store: FileTokenStore) -> int:
    async with DaitemClient(creds.email, creds.password, token_store=store) as client:
        systems = await client.account.list_systems()
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
    status = await system.panel.read()
    try:
        transmitter = await system.panel.transmitter_online()
    except DaitemError:
        transmitter = None  # the state was read, so this alone is no reason to fail
    payload = {
        "system_id": system.system_id,
        "panel_state": status.panel_state.value,
        "armed": status.is_armed,
        "arming": status.is_arming,
        "active_groups": status.active_groups,
        "transmitter_online": transmitter,
    }
    _emit(
        payload,
        [
            f"State       : {status.panel_state.value}",
            f"Groups      : {status.active_groups or 'none active'}",
            f"Transmitter : {_ONLINE[transmitter]}",
        ],
        args.json,
    )
    return EXIT_OK


_ONLINE = {True: "online", False: "offline", None: "unknown"}


async def _cmd_devices(args: argparse.Namespace, system: DaitemSystem) -> int:
    inventory = await system.inventory.read()
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
                "triggered": device.triggered,
            }
        )
        alerts = [*faults, *(["TRIGGERED"] if device.triggered else [])]
        device_lines.append(
            f"{device.kind:<12} {device.name:<28} group={device.group} {', '.join(alerts) or '-'}"
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
    presets = await system.capabilities.presets()
    payload: dict[str, Any] = {"presets": presets}
    lines = [f"{item.get('id')}\t{item.get('name')}" for item in presets] or ["No preset defined."]
    _emit(payload, lines, args.json)
    return EXIT_OK


async def _cmd_modes(args: argparse.Namespace, system: DaitemSystem) -> int:
    modes = sorted(mode.value for mode in await system.capabilities.arm_modes())
    discovered = system.capabilities.discovered
    lines = list(modes)
    if not discovered:
        lines.append("Presets could not be read (panel busy?): only away is certain.")
    _emit({"modes": modes, "discovered": discovered}, lines, args.json)
    return EXIT_OK


async def _cmd_control(args: argparse.Namespace, system: DaitemSystem) -> int:
    arming = args.command == "arm"
    groups: list[int] | None = args.groups
    if groups is not None and not groups:
        # An empty list must not fall through to arming or disarming every group.
        print("--groups needs at least one group id.", file=sys.stderr)
        return EXIT_USAGE
    if groups:
        action = f"{args.command} groups {', '.join(map(str, groups))}"
    else:
        action = f"arm ({args.mode})" if arming else "disarm"
    if not _confirm(f"Really {action} the alarm?", args.yes):
        return EXIT_USAGE

    if groups:
        status = await system.commands.arm_groups({group: arming for group in groups})
    elif arming:
        status = await system.commands.arm(_ARM_MODES[args.mode])
    else:
        status = await system.commands.disarm()
    if arming and args.wait:
        try:
            status = await system.panel.wait_settled(timeout=args.wait)
        except DaitemError as err:
            # The command went through: a failure here must not make a script send it again.
            print(f"Armed, but the wait for the exit delay failed: {err}", file=sys.stderr)

    _emit(
        {"panel_state": status.panel_state.value, "active_groups": status.active_groups},
        [f"State: {status.panel_state.value}"],
        args.json,
    )
    return EXIT_OK
