"""Smoke test of pydaitem against the live API.

The async client is a full port of the reference sync client: unit tests cover neither
the authentication flow (cookies, redirect, form encoding) nor the transport. This script
fills that gap by exercising the real sequence.

Not shipped: the `scripts/` folder is excluded from the PyPI package.

WARNING: without `--dry-run` this ARMS then DISARMS a real alarm. Disarming is guaranteed
on exit, even on error.

Usage:
    python scripts/smoke.py --env-file ../daitem-api-research/client/.env --dry-run
    python scripts/smoke.py --env-file ../daitem-api-research/client/.env
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from pydaitem import (
    DaitemClient,
    DaitemNoSessionError,
    DaitemSessionBusyError,
    DaitemSystem,
)


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"Missing variable: {name}")
    return value


def log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description="pydaitem smoke test")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).parent.parent / ".env")
    parser.add_argument("--dry-run", action="store_true", help="skip every arming command")
    args = parser.parse_args()

    load_env(args.env_file)
    email = require("DAITEM_EMAIL")
    password = require("DAITEM_PASSWORD")
    master_code = require("DAITEM_MASTER_CODE")

    started = time.monotonic()
    async with DaitemClient(email, password) as client:
        # 1. Authentication: the most fragile part of the port.
        log("auth", f"signing in as {email}…")
        await client.login()
        user = await client.account.get_user()
        log("auth", f"OK — {user.get('firstName')} {user.get('lastName')}")

        # 2. Systems.
        systems = await client.account.list_systems()
        log("systems", ", ".join(f"{s.id} « {s.name} » role={s.role}" for s in systems))
        system = DaitemSystem(client, systems[0].id, master_code)
        log("modes", f"supported arming modes: {sorted(await system.capabilities.arm_modes())}")

        # 3. Opportunistic read: tells whether a session already exists.
        try:
            await client.panel.get_state(system.system_id)
            log("session", "a session already exists (mobile app open?)")
            session_held_by_other = True
        except DaitemNoSessionError:
            log("session", "no session open, the client will open its own")
            session_held_by_other = False

        status = await system.read_status()
        log("state", f"panel_state={status.panel_state} groups={status.active_groups}")

        # 4. Inventory.
        inventory = await system.read_inventory()
        anomalies = sorted(f.value for f in inventory.central_anomalies.faults)
        log(
            "inventory",
            f"{len(inventory.sensors)} detectors, {len(inventory.controls)} controls, "
            f"hasIO={inventory.has_io}, anomalies={anomalies or 'none'}",
        )

        # 5. Command cycle.
        if args.dry_run:
            log("command", "--dry-run: no command sent")
        elif session_held_by_other:
            log("command", "session held by another device: cycle skipped")
        else:
            await run_command_cycle(system)

    log("done", f"finished in {time.monotonic() - started:.1f}s")
    return 0


async def run_command_cycle(system: DaitemSystem) -> None:
    """Arm then disarm through the façade, with disarming guaranteed even on error."""
    try:
        log("command", "ARMING (all groups)…")
        status = await system.commands.arm_away()
        log("command", f"immediate response: {status.panel_state}")

        # The façade releases the session between calls, so we simply re-read.
        for _ in range(30):
            await asyncio.sleep(2)
            status = await system.read_status()
            if not status.is_arming:
                break
        log("command", f"settled state: {status.panel_state}")

        log("command", "DISARMING…")
        status = await system.commands.disarm()
        log("command", f"state: {status.panel_state}")
    except DaitemSessionBusyError as exc:
        log("command", f"session busy: {exc}")
    finally:
        # Safety net: never leave the alarm armed. It catches Exception, not just
        # DaitemError: an unexpected bug is exactly when the net matters most, and a
        # narrow except once let a crash leave the alarm armed.
        try:
            final = await system.read_status()
            if final.is_armed or final.is_arming:
                log("cleanup", f"state {final.panel_state}, safety disarm…")
                final = await system.commands.disarm()
            log("cleanup", f"final state: {final.panel_state}")
        except Exception as exc:
            log("cleanup", f"SAFETY DISARM FAILED ({exc}) - CHECK THE ALARM MANUALLY")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
