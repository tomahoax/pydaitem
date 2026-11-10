"""Recurring arm/disarm programs: `system.schedule.*`."""

from __future__ import annotations

from ..models import Schedule, ScheduleProgram
from ..models._shared import parse
from .state import _SystemState, bounded


class _Schedule:
    """Owner accounts only: others get `DaitemForbiddenError`.

    Every call holds a panel session, so may raise the session errors.
    """

    def __init__(self, state: _SystemState) -> None:
        self._state = state

    @bounded("schedule.read")
    async def read(self) -> Schedule:
        """The installation's recurring arm/disarm programs.

        Read inside a panel session, like the widgets endpoint. Owner-only: a restricted
        account raises `DaitemForbiddenError`.
        """
        state = self._state
        async with state.session():
            data = await state.client.schedule.get(state.system_id)
        return parse(lambda: Schedule.from_json(data), "schedule")

    @bounded("schedule.update_program")
    async def update_program(self, program: ScheduleProgram) -> ScheduleProgram:
        """Update an existing scheduled program.

        Creating one is left to `client.schedule.add_program`.
        """
        state = self._state
        async with state.session():
            data = await state.sending(
                state.client.schedule.update_program(state.system_id, program.to_json())
            )
        return parse(lambda: ScheduleProgram.from_json(data), "schedule program")

    @bounded("schedule.delete_program")
    async def delete_program(self, program_id: int) -> None:
        state = self._state
        async with state.session():
            await state.sending(state.client.schedule.delete_program(state.system_id, program_id))

    @bounded("schedule.set_active")
    async def set_active(self, active: bool) -> None:
        """Master switch for the whole schedule, independent of each program."""
        state = self._state
        async with state.session():
            await state.sending(state.client.schedule.set_active(state.system_id, active))
