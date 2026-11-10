"""The event log: `system.logbook.*`."""

from __future__ import annotations

from ..models import LogEntry
from ..models._shared import parse
from .extras import with_session_if_needed
from .state import _SystemState


class _Logbook:
    def __init__(self, state: _SystemState) -> None:
        self._state = state

    async def read(self) -> list[LogEntry]:
        """The event log, newest first. Owner accounts only, others get `DaitemForbiddenError`.

        Asynchronous on the API side, so this takes a few seconds, and the answer can be
        large. Titles are translation keys, kept as they are. A panel session, when the API
        asks for one, covers the job creation only: the wait never holds the panel. May
        raise the session errors when it opens one, and `DaitemConnectionError` when the
        API has not prepared the log in time.
        """
        state = self._state
        # The budget covers the job creation: the wait for the log has its own bound.
        async with state.deadline("logbook.read"):
            job = await with_session_if_needed(
                state, lambda: state.client.logbook.create_job(state.system_id)
            )
        # The panel is released in the background: wait for it, so the slow wait for the
        # log never overlaps a session the mobile app could need.
        await state.client.panel.wait_released()
        entries = await state.client.logbook.wait_job(job)
        return parse(lambda: [LogEntry.from_json(entry) for entry in entries], "logbook")
