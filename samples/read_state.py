"""Read the alarm state, the device inventory and the active faults.

Read-only: this never arms or disarms anything.

    python samples/read_state.py --env-file ~/.daitem.env
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from pydaitem import connect, resolve_credentials


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, help="KEY=VALUE file holding credentials")
    args = parser.parse_args()

    creds = resolve_credentials(env_file=args.env_file)

    async with connect(
        creds.email, creds.password, creds.code, system_id=creds.system_id
    ) as system:
        status = await system.read_status()
        print(f"\nState   : {status.panel_state}")
        print(f"Groups  : {status.active_groups or 'none active'}")

        inventory = await system.read_inventory()
        print(f"Panel   : {inventory.central_type}, I/O board={inventory.has_io}")
        print(f"Devices : {len(inventory.sensors)} detectors, {len(inventory.controls)} controls")

        faults = inventory.central_anomalies.faults
        print(f"Faults  : {sorted(f.value for f in faults) if faults else 'none'}")


if __name__ == "__main__":
    asyncio.run(main())
