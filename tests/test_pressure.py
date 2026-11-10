"""Calls the library does not send: shared reads, kept answers, a breaker on a refusing API.

Each request reaches the Daitem servers, and several clients (an integration, a script, the
mobile app) share them. A call answered without the network is one the API never sees.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from pydaitem import (
    DaitemApiError,
    DaitemRateLimitedError,
    DaitemSystem,
    DaitemUsageError,
    PanelState,
    Remedy,
)
from pydaitem.client import pressure
from pydaitem.testing import FakeDaitem

SID = 123456


@pytest.fixture
async def fake() -> AsyncIterator[FakeDaitem]:
    async with FakeDaitem(system_id=SID, latency=0.02) as service:
        yield service


@pytest.fixture
async def system(fake: FakeDaitem) -> AsyncIterator[DaitemSystem]:
    async with fake.client() as client:
        await client.account.list_systems()
        yield DaitemSystem(client, fake.system_id, fake.code)


async def test_concurrent_reads_share_one_request(fake: FakeDaitem, system: DaitemSystem) -> None:
    start = len(fake.requests)
    first, second, third = await asyncio.gather(
        system.panel.read(), system.panel.read(), system.panel.read()
    )
    await system.client.panel.wait_released()
    assert first.panel_state is second.panel_state is third.panel_state is PanelState.DISARMED
    assert len(fake.requests) - start == 3  # state, connect, disconnect: once for all three
    assert fake.sessions_opened == 1


async def test_concurrent_inventory_reads_share_one_request(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    start = len(fake.requests)
    await asyncio.gather(*(system.inventory.read() for _ in range(5)))
    assert len(fake.requests) - start == 1


async def test_a_cancelled_reader_leaves_the_read_to_the_others(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    first = asyncio.ensure_future(system.inventory.read())
    second = asyncio.ensure_future(system.inventory.read())
    await asyncio.sleep(0)
    first.cancel()
    assert (await second).central_type == "INTRUSION"
    with pytest.raises(asyncio.CancelledError):
        await first


async def test_reads_one_after_the_other_are_not_shared(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    """Sharing is for reads in flight together: a later read asks the panel again."""
    start = len(fake.requests)
    await system.inventory.read()
    await system.inventory.read()
    assert len(fake.requests) - start == 2


async def test_a_read_inside_ones_own_session_does_not_wait_for_itself(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    """Shared reads run in a task of their own, which would wait for the caller's lock."""
    fake.fail("GET", "/state", status=403, message="status.nottmsessionid")
    async with system.client.panel.session(fake.system_id, fake.code):
        # asyncio.timeout, not wait_for: before 3.12 wait_for runs the read in another task.
        with pytest.raises(DaitemUsageError, match="already open in this task"):
            async with asyncio.timeout(2):
                await system.panel.read()


# -- Answers kept for callers that accept them a little old ----------------------------


async def test_a_recent_enough_answer_costs_no_request(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    await system.inventory.read()
    await system.panel.read()
    await system.client.panel.wait_released()
    start = len(fake.requests)
    await system.inventory.read(max_age=60)
    await system.panel.read(max_age=60)
    assert len(fake.requests) == start


async def test_a_command_leaves_its_state_for_the_next_read(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    armed = await system.commands.arm_away()
    await system.client.panel.wait_released()
    start = len(fake.requests)
    assert (await system.panel.read(max_age=5)) is armed
    assert len(fake.requests) == start


# -- The breaker -------------------------------------------------------------------------

OVERLIMIT = "transmitter.connection.overlimit"


async def test_a_rate_limit_stops_the_next_calls_without_the_network(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    fake.fail("GET", "/configuration", message=OVERLIMIT)
    with pytest.raises(DaitemRateLimitedError):
        await system.inventory.read()
    start = len(fake.requests)
    with pytest.raises(DaitemRateLimitedError, match="not sent") as raised:
        await system.panel.read()
    assert raised.value.remedy is Remedy.RETRY_LATER
    assert len(fake.requests) == start
    assert system.client.stats.refused_locally == 1


async def test_the_panel_is_released_even_while_the_breaker_is_open(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    """A release refused locally would leave the mobile app locked out."""
    fake.fail("GET", "/configuration", message=OVERLIMIT)
    async with system.client.panel.session(fake.system_id, fake.code):
        with pytest.raises(DaitemRateLimitedError):
            await system.inventory.read()
    await system.client.panel.wait_released()
    assert not fake.session_open


async def test_the_breaker_lets_a_request_through_once_the_pause_is_over(
    fake: FakeDaitem, system: DaitemSystem, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pressure, "FIRST_PAUSE", 0.1)
    fake.fail("GET", "/configuration", message=OVERLIMIT)
    with pytest.raises(DaitemRateLimitedError):
        await system.inventory.read()
    await asyncio.sleep(0.15)
    assert (await system.inventory.read()).central_type == "INTRUSION"
    assert system.client._state.breaker.remaining() == 0


async def test_gateway_errors_open_the_breaker_but_a_business_error_does_not(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    fake.fail("GET", "/configuration", status=500, times=5)  # untyped 500s: not a signal
    for _ in range(5):
        with pytest.raises(DaitemApiError):
            await system.inventory.read()
    assert system.client._state.breaker.remaining() == 0

    fake.fail("GET", "/configuration", status=502, times=pressure.GATEWAY_FAILURES)
    for _ in range(pressure.GATEWAY_FAILURES):
        with pytest.raises(DaitemApiError):
            await system.inventory.read()
    assert system.client._state.breaker.remaining() > 0


# -- Counters ----------------------------------------------------------------------------


async def test_the_counters_match_what_the_service_received(
    fake: FakeDaitem, system: DaitemSystem
) -> None:
    before = system.client.stats
    await system.read_snapshot()
    await system.commands.arm_away()
    await system.client.panel.wait_released()
    stats = system.client.stats
    topaze = [r for r in fake.requests if " /topaze/" in r]
    assert stats.total_requests == len(topaze)
    assert stats.sessions_opened - before.sessions_opened == 2
    assert stats.session_seconds > 0
    assert stats.requests["POST /topaze/v5/systems/{id}/connect"] == 2


async def test_a_slow_job_is_polled_less_and_less_often(monkeypatch: pytest.MonkeyPatch) -> None:
    """Waits of 1, 2, 4, then 4 s at most for a job polled every second at first."""
    from pydaitem.client import jobs

    waits: list[float] = []

    async def sleep(delay: float) -> None:
        waits.append(delay)

    polls = iter([{"status": "PENDING"}] * 5 + [{"status": "DONE", "response": []}])

    class Transport:
        async def request(self, method: str, path: str) -> object:
            return next(polls)

    monkeypatch.setattr(jobs.asyncio, "sleep", sleep)
    await jobs.poll_job(Transport(), "/topaze/x", timeout=60, interval=1.0, what="job")  # type: ignore[arg-type]
    assert waits == [1.0, 2.0, 4.0, 4.0, 4.0]
