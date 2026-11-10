"""Commands that drive a real alarm: `system.commands.*`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from ..const import ArmMode
from ..exceptions import DaitemUsageError
from ..models import SystemStatus
from .capabilities import _Capabilities
from .state import _SystemState, bounded


class _Commands:
    """Each command holds a panel session, so may raise the session errors.

    A command the panel does not confirm raises `DaitemCommandError`. With
    `CommandStatus.TIMEOUT` it may still have run, and so may a command that ended in
    `DaitemConnectionError`, since writes are never replayed: read the state before sending
    it again.
    """

    def __init__(self, state: _SystemState, capabilities: _Capabilities) -> None:
        self._state = state
        self._capabilities = capabilities

    @bounded("commands.arm")
    async def arm(self, mode: ArmMode = ArmMode.AWAY) -> SystemStatus:
        """Arm in the given mode, resolving any preset index internally.

        Raises `DaitemUsageError`, before the command is sent, when the installation does
        not offer `mode` (see `capabilities.arm_modes()`). When the modes are not known yet,
        they are read in the command's own session: an error reading them is raised as it
        is, rather than taken for a mode the installation lacks.
        """
        state = self._state
        if mode is ArmMode.AWAY:
            return await self._command(lambda sid: state.sending(state.client.commands.arm(sid)))

        capabilities = self._capabilities
        if capabilities.discovered and capabilities._preset_for(mode) is None:
            raise DaitemUsageError(f"This installation does not support the {mode} arming mode")

        async def action(system_id: int) -> SystemStatus:
            # Not discovered yet: read the presets in this command's own session rather than
            # in one of their own, which would hold the panel twice in a row.
            if not capabilities.discovered:
                await capabilities._discover()
            preset = capabilities._preset_for(mode)
            if preset is None:
                raise DaitemUsageError(f"This installation does not support the {mode} arming mode")
            return await state.sending(
                state.client.commands.start_partial_arming(system_id, preset=preset)
            )

        return await self._command(action)

    async def arm_away(self) -> SystemStatus:
        """`arm(ArmMode.AWAY)`, which every installation offers."""
        return await self.arm(ArmMode.AWAY)

    async def arm_presence(self) -> SystemStatus:
        """`arm(ArmMode.PRESENCE)`."""
        return await self.arm(ArmMode.PRESENCE)

    @bounded("commands.disarm")
    async def disarm(self) -> SystemStatus:
        """Disarm every group."""
        state = self._state
        return await self._command(lambda sid: state.sending(state.client.commands.disarm(sid)))

    @bounded("commands.arm_groups")
    async def arm_groups(self, groups: Mapping[int, bool]) -> SystemStatus:
        """Arm or disarm specific groups directly, bypassing named presets.

        Mirrors the mobile app's per-group toggle. Unlike `arm(ArmMode.PARTIAL)` this does
        not depend on how a preset is configured or named on the installation, and drives
        raw states (`group`/`tempogroup`) already validated in production, at the cost of
        losing whatever behaviour the preset itself configures beyond group membership
        (delay, siren).
        """

        async def action(system_id: int) -> SystemStatus:
            return await self._state.sending(
                self._state.client.commands.arm_groups(system_id, groups)
            )

        return await self._command(action)

    async def _command(self, action: Callable[[int], Awaitable[SystemStatus]]) -> SystemStatus:
        """Hold a session for exactly the length of one command, then release it.

        The panel accepts a single session at a time across all accounts, so holding one
        any longer would lock out the mobile app.
        """
        state = self._state
        async with state.session():
            status: SystemStatus = await action(state.system_id)
        # The state the command answered with is the freshest there is.
        state.keep("panel.read", status)
        return status
