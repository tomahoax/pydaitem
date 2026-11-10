"""`pydaitem.testing`: the fake service drives the real client through the edge cases.

These tests are also the examples a consumer copies: each one is a situation an integration
must handle, played end to end, sign-in included.
"""

from __future__ import annotations

import pytest

from pydaitem import (
    ArmMode,
    DaitemAuthError,
    DaitemBadCodeError,
    DaitemCommandError,
    DaitemConnectionError,
    DaitemSessionBusyError,
    DaitemSystem,
    DaitemTransmitterOfflineError,
    MemoryTokenStore,
    PanelState,
    Remedy,
)
from pydaitem.testing import FakeDaitem, status


async def test_read_and_arm_through_the_facade() -> None:
    async with FakeDaitem() as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        assert (await system.panel.read()).panel_state is PanelState.DISARMED
        assert (await system.inventory.read()).sensors[0].name == "Front door"
        assert await system.capabilities.arm_modes() == {ArmMode.AWAY, ArmMode.PRESENCE}

        assert (await system.commands.arm(ArmMode.PRESENCE)).panel_state is (
            PanelState.ARMED_PRESENCE
        )
        assert (await system.commands.disarm()).panel_state is PanelState.DISARMED
        # Every session was released: the mobile app is never locked out.
        await client.panel.wait_released()
        assert not fake.session_open


async def test_the_exit_delay_settles() -> None:
    async with FakeDaitem(exit_delay=0.2) as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        assert (await system.commands.arm_away()).is_arming
        settled = await system.panel.wait_settled(timeout=5, interval=0.05)
        assert settled.panel_state is PanelState.ARMED_FULL


async def test_another_device_holding_the_panel() -> None:
    async with FakeDaitem(held_by="iPhone") as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        # A read uses the other device's session...
        assert (await system.panel.read()).panel_state is PanelState.DISARMED
        # ...a command cannot open one.
        with pytest.raises(DaitemSessionBusyError) as raised:
            await system.commands.arm_away()
        assert raised.value.remedy is Remedy.RETRY_LATER
        assert raised.value.placeholders == {"holder": "iPhone"}
        # Arming mode discovery degrades instead of failing, and tries again later.
        assert await system.capabilities.arm_modes() == {ArmMode.AWAY}
        assert not system.capabilities.discovered


async def test_a_wrong_alarm_code() -> None:
    async with FakeDaitem() as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, "0000")
        with pytest.raises(DaitemBadCodeError) as raised:
            await system.panel.read()
        assert raised.value.remedy is Remedy.ASK_CODE


async def test_a_wrong_password() -> None:
    async with FakeDaitem() as fake, fake.client(password="wrong") as client:
        with pytest.raises(DaitemAuthError) as raised:
            await client.account.list_systems()
        assert raised.value.remedy is Remedy.ASK_CREDENTIALS


async def test_the_transmitter_offline() -> None:
    async with FakeDaitem(online=False) as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        with pytest.raises(DaitemTransmitterOfflineError) as raised:
            await system.panel.read()
        assert raised.value.remedy is Remedy.UNAVAILABLE
        assert await system.panel.transmitter_online() is False


async def test_a_command_the_panel_does_not_confirm() -> None:
    async with FakeDaitem(command_status="CMD TIMEOUT") as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        with pytest.raises(DaitemCommandError) as raised:
            await system.commands.arm_away()
        assert raised.value.remedy is Remedy.CHECK_STATE
        await client.panel.wait_released()
        assert not fake.session_open


async def test_a_command_whose_answer_is_lost() -> None:
    async with FakeDaitem() as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        fake.drop("POST", "/sendSystemCommand")
        with pytest.raises(DaitemConnectionError) as raised:
            await system.commands.arm_away()
        assert raised.value.remedy is Remedy.CHECK_STATE
        # Sent once, never replayed, and the session still released.
        assert (
            fake.requests.count(
                f"POST /topaze/v1/action/systems/{fake.system_id}/sendSystemCommand"
            )
            == 1
        )
        await client.panel.wait_released()
        assert not fake.session_open


async def test_an_injected_server_message_is_typed() -> None:
    async with FakeDaitem() as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        fake.fail("GET", "/configuration", message="transmitter.error.ttdisconnected")
        with pytest.raises(DaitemTransmitterOfflineError) as raised:
            await system.inventory.read()
        assert raised.value.code == "transmitter_offline"
        assert (await system.inventory.read()).central_type == "INTRUSION"  # once only
        # A rate limit would also stop the next calls for a while: see test_pressure.py.


async def test_a_restart_resumes_from_the_stored_token() -> None:
    store = MemoryTokenStore()
    async with FakeDaitem() as fake:
        async with fake.client(token_store=store) as client:
            await client.account.list_systems()
        logins = fake.requests.count("POST /realms/daitem/login-actions/authenticate")
        async with fake.client(token_store=store) as client:
            await client.account.list_systems()
        assert fake.requests.count("POST /realms/daitem/login-actions/authenticate") == logins

        fake.revoke_tokens()
        async with fake.client(token_store=store) as client:
            await client.account.list_systems()  # signs in again, quietly
        assert fake.requests.count("POST /realms/daitem/login-actions/authenticate") == logins + 1


def test_status_builds_any_panel_state_but_triggered() -> None:
    built = status(PanelState.ARMED_GROUPS, groups=[1, 3])
    assert built.panel_state is PanelState.ARMED_GROUPS and built.active_groups == [1, 3]
    assert status(PanelState.UNKNOWN).panel_state is PanelState.UNKNOWN
    with pytest.raises(ValueError):
        status(PanelState.TRIGGERED)


async def test_check_code_tells_a_wrong_code_from_a_busy_panel() -> None:
    async with FakeDaitem() as fake, fake.client() as client:
        await DaitemSystem(client, fake.system_id, fake.code).panel.check_code()
        await client.panel.wait_released()
        assert fake.sessions_opened == 1 and not fake.session_open
        with pytest.raises(DaitemBadCodeError):
            await DaitemSystem(client, fake.system_id, "0000").panel.check_code()
        fake.held_by = "iPhone"
        with pytest.raises(DaitemSessionBusyError):
            await DaitemSystem(client, fake.system_id, fake.code).panel.check_code()


async def test_a_snapshot_keeps_the_faults_when_the_state_fails() -> None:
    async with FakeDaitem(online=False) as fake, fake.client() as client:
        snapshot = await DaitemSystem(client, fake.system_id, fake.code).read_snapshot()
        assert snapshot.status is None and snapshot.inventory is not None
        assert snapshot.errors["status"].remedy is Remedy.UNAVAILABLE
        assert set(snapshot.errors) == {"status"}


async def test_a_stalled_answer_ends_in_the_clients_timeout() -> None:
    async with FakeDaitem() as fake, fake.client(timeout=0.2) as client:
        fake.stall("GET", "/configuration", times=3)  # the first attempt and both retries
        with pytest.raises(DaitemConnectionError):
            await DaitemSystem(client, fake.system_id, fake.code).inventory.read()
