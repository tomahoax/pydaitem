"""Measure what each façade call costs: requests, panel sessions and time, on a slow network.

Runs against pydaitem.testing.FakeDaitem, so it needs no account and touches no alarm. Each
answer waits `--latency` seconds, as a round trip to the Daitem servers would. The figures
compare versions of the library with each other: they do not predict the real API's times.

    python scripts/bench.py --latency 0.1
"""

from __future__ import annotations

import argparse
import asyncio
import time
from collections.abc import Awaitable, Callable

from pydaitem import ArmMode, DaitemSystem
from pydaitem.testing import FakeDaitem


async def measure(
    fake: FakeDaitem, system: DaitemSystem, name: str, call: Callable[[], Awaitable[object]]
) -> None:
    requests, sessions = len(fake.requests), fake.sessions_opened
    started = time.monotonic()
    await call()
    elapsed = time.monotonic() - started
    # The release may still run: it is part of the load, not of the caller's wait.
    await system.client.panel.wait_released()
    print(
        f"{name:<44} {len(fake.requests) - requests:>3} requests "
        f"{fake.sessions_opened - sessions:>2} sessions {elapsed * 1000:>6.0f} ms"
    )


async def main(latency: float) -> None:
    async with FakeDaitem(latency=latency, exit_delay=1.0) as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        await client.account.list_systems()  # signed in: the sign-in is not measured

        await measure(fake, system, "panel.read(), panel free", system.panel.read)
        await measure(fake, system, "inventory.read()", system.inventory.read)
        await measure(fake, system, "read_snapshot() (a poll cycle)", system.read_snapshot)
        await measure(fake, system, "read_extras()", system.read_extras)
        await measure(
            fake,
            system,
            "commands.arm(PRESENCE), modes unknown",
            lambda: system.commands.arm(ArmMode.PRESENCE),
        )
        await measure(fake, system, "commands.disarm()", system.commands.disarm)
        await measure(fake, system, "capabilities.presets()", system.capabilities.presets)
        await measure(
            fake,
            system,
            "3 concurrent panel.read()",
            lambda: asyncio.gather(system.panel.read(), system.panel.read(), system.panel.read()),
        )
        await measure(
            fake, system, "arm_away() + wait_settled() (1 s delay)", lambda: _arm_and_wait(system)
        )


async def _arm_and_wait(system: DaitemSystem) -> None:
    await system.commands.arm_away()
    await system.panel.wait_settled(interval=0.25)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--latency", type=float, default=0.1, help="seconds per answer")
    asyncio.run(main(parser.parse_args().latency))
