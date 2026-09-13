"""Commands that drive a real alarm: `system.commands.*`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from ..const import ArmMode
from ..exceptions import DaitemError
from ..models import SystemStatus
from .capabilities import _Capabilities
from .state import _SystemState


class _Commands:
    def __init__(self, state: _SystemState, capabilities: _Capabilities) -> None:
        self._state = state
        self._capabilities = capabilities

    async def arm(self, mode: ArmMode = ArmMode.AWAY) -> SystemStatus:
        """Arm in the given mode, resolving any preset index internally."""
        if mode is ArmMode.AWAY:
            return await self._command(self._state.client.commands.arm)

        await self._capabilities.arm_modes()
        preset = self._capabilities.preset_for(mode)
        if preset is None:
            raise DaitemError(f"This installation does not support the {mode} arming mode")

        async def action(system_id: int) -> SystemStatus:
            return await self._state.client.commands.start_partial_arming(system_id, preset=preset)

        return await self._command(action)

    async def arm_away(self) -> SystemStatus:
        return await self.arm(ArmMode.AWAY)

    async def arm_presence(self) -> SystemStatus:
        return await self.arm(ArmMode.PRESENCE)

    async def disarm(self) -> SystemStatus:
        return await self._command(self._state.client.commands.disarm)

    async def arm_groups(self, groups: Mapping[int, bool]) -> SystemStatus:
        """Arm or disarm specific groups directly, bypassing named presets.

        Mirrors the mobile app's per-group toggle. Unlike `arm(ArmMode.PARTIAL)` this does
        not depend on how a preset is configured or named on the installation, and drives
        raw states (`group`/`tempogroup`) already validated in production, at the cost of
        losing whatever behaviour the preset itself configures beyond group membership
        (delay, siren).
        """

        async def action(system_id: int) -> SystemStatus:
            return await self._state.client.commands.arm_groups(system_id, groups)

        return await self._command(action)

    async def _command(self, action: Callable[[int], Awaitable[SystemStatus]]) -> SystemStatus:
        """Hold a session for exactly the length of one command, then release it.

        The panel accepts a single session at a time across all accounts, so holding one
        any longer would lock out the mobile app.
        """
        state = self._state
        async with state.client.panel.session(state.system_id, state.code):
            status: SystemStatus = await action(state.system_id)
        return status
