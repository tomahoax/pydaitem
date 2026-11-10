"""Smoke test of pydaitem against the live API, run by a maintainer before a release.

The unit tests never call the API. This script replays the real sequence: Keycloak
sign-in, system list, state, inventory, then an arm and disarm cycle.

Not shipped: the `scripts/` folder is left out of the PyPI package. It needs the library
installed, for instance with `pip install -e .`.

WARNING: without `--dry-run` this ARMS then DISARMS a real alarm. Disarming is attempted
on exit, even on error.

Usage:
    python scripts/smoke.py --env-file ~/.daitem.env --dry-run
    python scripts/smoke.py --env-file ~/.daitem.env
"""

from __future__ import annotations

import argparse
import asyncio
import time
from pathlib import Path

from pydaitem import (
    DaitemClient,
    DaitemNoSessionError,
    DaitemSessionBusyError,
    DaitemSystem,
    resolve_credentials,
)


def log(step: str, message: str) -> None:
    print(f"[{step}] {message}", flush=True)


async def main() -> int:
    parser = argparse.ArgumentParser(description="pydaitem smoke test")
    parser.add_argument("--env-file", type=Path, help="KEY=VALUE file holding credentials")
    parser.add_argument("--dry-run", action="store_true", help="skip every arming command")
    args = parser.parse_args()

    creds = resolve_credentials(env_file=args.env_file)

    started = time.monotonic()
    async with DaitemClient(creds.email, creds.password) as client:
        # 1. Authentication, which the unit tests only cover against a fake server.
        log("auth", f"signing in as {creds.email}...")
        await client.login()
        user = await client.account.get_user()
        log("auth", f"OK, {user.get('firstName')} {user.get('lastName')}")

        # 2. Systems.
        systems = await client.account.list_systems()
        log("systems", ", ".join(f'{s.id} "{s.name}" role={s.role}' for s in systems))
        system = DaitemSystem(client, creds.system_id or systems[0].id, creds.code)
        log("modes", f"supported arming modes: {sorted(await system.capabilities.arm_modes())}")

        # 3. Opportunistic read: tells whether a session already exists.
        try:
            await client.panel.get_state(system.system_id)
            log("session", "a session already exists (mobile app open?)")
            session_held_by_other = True
        except DaitemNoSessionError:
            log("session", "no session open, the client will open its own")
            session_held_by_other = False

        status = await system.panel.read()
        log("state", f"panel_state={status.panel_state} groups={status.active_groups}")

        # 4. Inventory.
        inventory = await system.inventory.read()
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
    """Arm then disarm through the façade, with disarming attempted even on error."""
    try:
        log("command", "ARMING (all groups)...")
        status = await system.commands.arm_away()
        log("command", f"immediate response: {status.panel_state}")

        status = await system.panel.wait_settled(timeout=60)
        log("command", f"settled state: {status.panel_state}")

        log("command", "DISARMING...")
        status = await system.commands.disarm()
        log("command", f"state: {status.panel_state}")
    except DaitemSessionBusyError as exc:
        log("command", f"session busy: {exc}")
    finally:
        # Safety net: never leave the alarm armed. It catches Exception, not just
        # DaitemError: an unexpected bug is exactly when the net matters most, and a
        # narrow except once let a crash leave the alarm armed.
        try:
            final = await system.panel.read()
            if final.is_armed or final.is_arming:
                log("cleanup", f"state {final.panel_state}, safety disarm...")
                final = await system.commands.disarm()
            log("cleanup", f"final state: {final.panel_state}")
        except Exception as exc:
            log("cleanup", f"SAFETY DISARM FAILED ({exc}), CHECK THE ALARM MANUALLY")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
