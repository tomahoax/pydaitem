"""The exact requests each façade call sends, frozen.

Every request goes to the Daitem servers, and every panel session keeps the mobile app out:
the sequences are the library's cost. A change that adds a request shows up here as a
failing test, and a change that removes one rewrites the expected list on purpose.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable

import pytest

from pydaitem import ArmMode, DaitemSystem
from pydaitem.testing import FakeDaitem

SID = 123456
SYSTEM = f"/v5/systems/{SID}"
STATE = f"GET {SYSTEM}/state"
CONNECT = f"POST {SYSTEM}/connect"
DISCONNECT = f"POST {SYSTEM}/disconnect"
INVENTORY = f"GET /v2/systems/{SID}/configuration"


@pytest.fixture
async def fake() -> AsyncIterator[FakeDaitem]:
    async with FakeDaitem(system_id=SID) as service:
        yield service


@pytest.fixture
async def system(fake: FakeDaitem) -> AsyncIterator[DaitemSystem]:
    async with fake.client() as client:
        await client.account.list_systems()  # signed in: the sign-in is not counted below
        yield DaitemSystem(client, fake.system_id, fake.code)


async def sent(fake: FakeDaitem, system: DaitemSystem, call: Awaitable[object]) -> list[str]:
    """The requests `call` sent, its panel release included, without the `/topaze` prefix."""
    start = len(fake.requests)
    await call
    await system.client.panel.wait_released()
    return [r.replace("/topaze", "", 1) for r in fake.requests[start:]]


async def test_a_read_with_the_panel_free(fake: FakeDaitem, system: DaitemSystem) -> None:
    # Connect answers with the state: no second read while the panel is held.
    assert await sent(fake, system, system.panel.read()) == [STATE, CONNECT, DISCONNECT]


async def test_a_read_while_the_app_holds_the_panel(fake: FakeDaitem, system: DaitemSystem) -> None:
    fake.held_by = "iPhone"
    assert await sent(fake, system, system.panel.read()) == [STATE]


async def test_the_inventory(fake: FakeDaitem, system: DaitemSystem) -> None:
    assert await sent(fake, system, system.inventory.read()) == [INVENTORY]


async def test_a_poll_cycle(fake: FakeDaitem, system: DaitemSystem) -> None:
    requests = await sent(fake, system, system.read_snapshot())
    # The inventory and the first read leave together, in either order.
    assert sorted(requests[:2]) == sorted([INVENTORY, STATE])
    assert requests[2:] == [CONNECT, DISCONNECT]


async def test_arming_mode_discovery(fake: FakeDaitem, system: DaitemSystem) -> None:
    widgets = f"GET /v1/widgets/systems/{SID}/users/1"
    assert await sent(fake, system, system.capabilities.arm_modes()) == [
        CONNECT,
        "GET /v1/user",
        widgets,
        DISCONNECT,
    ]
    # Read with the arming modes: the raw presets cost nothing more.
    assert await sent(fake, system, system.capabilities.presets()) == []


async def test_a_command(fake: FakeDaitem, system: DaitemSystem) -> None:
    command = f"POST /v1/action/systems/{SID}/sendSystemCommand"
    assert await sent(fake, system, system.commands.arm_away()) == [CONNECT, command, DISCONNECT]


async def test_a_partial_arming_before_discovery(fake: FakeDaitem, system: DaitemSystem) -> None:
    partial = f"POST /v1/action/systems/{SID}/startPartialArmingWidgetCommand/0"
    # The presets are read in the command's own session: the panel is held once, not twice.
    assert await sent(fake, system, system.commands.arm(ArmMode.PRESENCE)) == [
        CONNECT,
        "GET /v1/user",
        f"GET /v1/widgets/systems/{SID}/users/1",
        partial,
        DISCONNECT,
    ]


async def test_the_transmitter(fake: FakeDaitem, system: DaitemSystem) -> None:
    assert await sent(fake, system, system.panel.transmitter_online()) == [
        "GET /v5/systems",
        "POST /configuration/getConfiguration",
        "POST /installation/isConnected",
    ]
    assert await sent(fake, system, system.panel.transmitter_online()) == [
        "POST /installation/isConnected"
    ]


async def test_the_extras(fake: FakeDaitem, system: DaitemSystem) -> None:
    assert await sent(fake, system, system.read_extras()) == [
        f"GET {SYSTEM}/automatisms",
        f"GET /v1/systems/{SID}/cameras",
        f"GET /v6/systems/{SID}/videos",
    ]


async def test_a_blocked_discovery_is_made_by_the_next_read(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    """The retry rides on the session the read opens anyway, rather than one of its own."""
    fake.held_by = "iPhone"
    assert await system.capabilities.arm_modes() == {ArmMode.AWAY}
    fake.held_by = None
    widgets = f"GET /v1/widgets/systems/{SID}/users/1"
    assert await sent(fake, system, system.panel.read()) == [
        STATE,
        CONNECT,
        "GET /v1/user",
        widgets,
        DISCONNECT,
    ]
    assert system.capabilities.discovered
    assert await sent(fake, system, system.capabilities.arm_modes()) == []
