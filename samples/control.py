"""Arm or disarm the alarm.

**This drives a real alarm.** It asks for confirmation before sending anything, and
prints the resulting state.

    python samples/control.py --env-file ~/.daitem.env arm-away
    python samples/control.py --env-file ~/.daitem.env disarm
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydaitem import (
    ArmMode,
    DaitemClient,
    DaitemSessionBusyError,
    DaitemSystem,
    resolve_credentials,
)

ACTIONS = {
    "arm-away": ArmMode.AWAY,
    "arm-presence": ArmMode.PRESENCE,
    "arm-partial": ArmMode.PARTIAL,
}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=[*ACTIONS, "disarm"])
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    creds = resolve_credentials(env_file=args.env_file)

    async with DaitemClient(creds.email, creds.password) as client:
        systems = await client.account.list_systems()
        system = DaitemSystem(client, creds.system_id or systems[0].id, creds.code)

        modes = await system.capabilities.arm_modes()
        print(f"Supported modes: {sorted(m.value for m in modes)}")

        if not args.yes:
            answer = input(f"Really {args.action} the alarm? [y/N] ")
            if answer.strip().lower() not in {"y", "yes"}:
                print("Cancelled.")
                return

        try:
            if args.action == "disarm":
                status = await system.commands.disarm()
            else:
                status = await system.commands.arm(ACTIONS[args.action])
        except DaitemSessionBusyError:
            print("Another device holds the panel session. Close the mobile app and retry.")
            return

        print(f"State: {status.panel_state}")


if __name__ == "__main__":
    asyncio.run(main())
