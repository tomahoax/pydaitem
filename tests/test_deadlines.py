"""Timeouts as guards: a slow or hung server bounds a call, never the caller's stability.

Each test hangs one request on the fake service and checks three things: the call ends
within its budget, it raises within `DaitemError` with the remedy that fits, and the panel
is free afterwards, since a session left open locks the mobile app out.
"""

from __future__ import annotations

import asyncio
import logging
import time

import pytest

from pydaitem import ArmMode, DaitemConnectionError, DaitemSystem, Remedy
from pydaitem.testing import FakeDaitem

BUDGET = 0.3


async def test_without_a_budget_a_call_is_bounded_by_its_requests_only() -> None:
    """Off by default: the request's own timeout bounds it, and a timeout is not resent."""
    async with FakeDaitem() as fake, fake.client(timeout=0.2) as client:
        fake.stall("GET", "/configuration")
        started = time.monotonic()
        with pytest.raises(DaitemConnectionError):
            await DaitemSystem(client, fake.system_id, fake.code).inventory.read()
        assert 0.2 <= time.monotonic() - started < 0.6  # one attempt, not three
        assert fake.requests.count(f"GET /topaze/v2/systems/{fake.system_id}/configuration") == 1


async def test_a_hung_read_ends_within_its_budget() -> None:
    async with FakeDaitem() as fake, fake.client(call_timeout=BUDGET) as client:
        fake.stall("GET", "/configuration", times=3)
        started = time.monotonic()
        with pytest.raises(DaitemConnectionError, match="no answer within") as raised:
            await DaitemSystem(client, fake.system_id, fake.code).inventory.read()
        assert time.monotonic() - started < 1.0
        assert raised.value.remedy is Remedy.RETRY_LATER


async def test_a_hung_command_says_to_check_the_state_and_frees_the_panel() -> None:
    async with FakeDaitem() as fake, fake.client(call_timeout=BUDGET) as client:
        fake.stall("POST", "/sendSystemCommand")
        with pytest.raises(DaitemConnectionError) as raised:
            await DaitemSystem(client, fake.system_id, fake.code).commands.arm_away()
        # It left: the panel may have obeyed.
        assert raised.value.remedy is Remedy.CHECK_STATE
        await client.panel.wait_released()
        assert not fake.session_open


async def test_a_hung_connect_is_not_taken_for_a_sent_command() -> None:
    async with FakeDaitem() as fake, fake.client(call_timeout=BUDGET) as client:
        fake.stall("POST", "/connect")
        with pytest.raises(DaitemConnectionError) as raised:
            await DaitemSystem(client, fake.system_id, fake.code).commands.disarm()
        assert raised.value.remedy is Remedy.RETRY_LATER


async def test_waiting_for_the_panel_counts_in_the_budget() -> None:
    """A command stuck behind a session another task holds ends, rather than waits on."""
    async with FakeDaitem() as fake, fake.client(call_timeout=BUDGET) as client:
        system = DaitemSystem(client, fake.system_id, fake.code)

        async def hold() -> None:
            async with client.panel.session(fake.system_id, fake.code):
                await asyncio.sleep(1.0)

        holder = asyncio.ensure_future(hold())
        await asyncio.sleep(0.05)
        with pytest.raises(DaitemConnectionError) as raised:
            await system.commands.arm(ArmMode.AWAY)
        assert raised.value.remedy is Remedy.RETRY_LATER
        await holder


async def test_calls_that_never_raise_report_a_budget_run_out() -> None:
    async with FakeDaitem() as fake, fake.client(call_timeout=BUDGET) as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        fake.stall("GET", "/state", times=3)
        snapshot = await system.read_snapshot()
        assert snapshot.inventory is not None
        assert isinstance(snapshot.errors["status"], DaitemConnectionError)

        fake.stall("GET", "/automatisms", times=3)
        extras = await system.read_extras()
        assert isinstance(extras.errors["automatisms"], DaitemConnectionError)
        assert extras.cameras == []

        fake.stall("POST", "/connect")
        assert await system.capabilities.arm_modes() == {ArmMode.AWAY}


async def test_a_session_held_too_long_is_released_for_the_other_devices(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with FakeDaitem() as fake, fake.client(max_session_hold=0.2) as client:
        with caplog.at_level(logging.WARNING, logger="pydaitem"):
            async with client.panel.session(fake.system_id, fake.code):
                await asyncio.sleep(0.5)
                assert not fake.session_open  # freed while the block still runs
        assert "held for more than 0.2 s" in caplog.text
        await client.panel.wait_released()
