"""Recurring arm/disarm programs: `system.schedule.*`."""

from __future__ import annotations

from ..models import Schedule, ScheduleProgram
from .state import _SystemState


class _Schedule:
    def __init__(self, state: _SystemState) -> None:
        self._state = state

    async def read(self) -> Schedule:
        """The installation's recurring arm/disarm programs.

        Assumed to need an open panel session, like the widgets endpoint (both were only
        ever observed following a `connect`) - not confirmed as a hard API requirement.

        Owner-only, confirmed live: a restricted account raises `DaitemForbiddenError`.
        """
        state = self._state
        async with state.client.panel.session(state.system_id, state.code):
            data = await state.client.schedule.get(state.system_id)
        return Schedule.from_json(data)

    async def update_program(self, program: ScheduleProgram) -> ScheduleProgram:
        """Update an existing scheduled program. Creating a new one is not supported, see
        `client.schedule.update_program`."""
        state = self._state
        async with state.client.panel.session(state.system_id, state.code):
            data = await state.client.schedule.update_program(state.system_id, program.to_json())
        return ScheduleProgram.from_json(data)

    async def delete_program(self, program_id: int) -> None:
        state = self._state
        async with state.client.panel.session(state.system_id, state.code):
            await state.client.schedule.delete_program(state.system_id, program_id)

    async def set_active(self, active: bool) -> None:
        """Master switch for the whole schedule, independent of each program."""
        state = self._state
        async with state.client.panel.session(state.system_id, state.code):
            await state.client.schedule.set_active(state.system_id, active)
