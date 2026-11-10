"""Scenarios: `system.scenarios.*`.

WARNING: running a scenario performs its actions, which may disarm the alarm.
"""

from __future__ import annotations

from ..models import Scenario, SystemStatus
from .extras import with_session_if_needed
from .state import _SystemState, bounded


class _Scenarios:
    def __init__(self, state: _SystemState) -> None:
        self._state = state

    @bounded("scenarios.read")
    async def read(self) -> list[Scenario]:
        """Every scenario, opening a panel session only if the read needs one.

        May raise the session errors when it does.
        """
        state = self._state
        return await with_session_if_needed(
            state, lambda: state.client.scenarios.list(state.system_id)
        )

    @bounded("scenarios.run")
    async def run(self, scenario: Scenario) -> SystemStatus:
        """Run `scenario` inside a panel session, and return the state that follows.

        Check `scenario.actions` first: a scenario may disarm the alarm. Holds a panel
        session, so may raise the session errors, and `DaitemCommandError` when the panel
        does not confirm it.
        """
        state = self._state
        async with state.session():
            return await state.sending(
                state.client.commands.start_scenario(state.system_id, scenario.id)
            )
