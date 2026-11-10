"""Driving automations: `system.automation.*`.

WARNING: drives real equipment, such as a gate or a garage door.
"""

from __future__ import annotations

from ..const.devices import AutomatismCommand
from ..exceptions import DaitemUsageError
from ..models import Automatism
from .extras import with_session_if_needed
from .state import _SystemState, bounded


def check_position(command: str, position: int | None) -> None:
    """Raise `DaitemUsageError` unless a position comes with POSITION, and only with it."""
    if command == AutomatismCommand.POSITION and position is None:
        raise DaitemUsageError("POSITION needs a position")
    if command != AutomatismCommand.POSITION and position is not None:
        raise DaitemUsageError(f"a position only goes with POSITION, not {command}")


class _Automation:
    def __init__(self, state: _SystemState) -> None:
        self._state = state

    @bounded("automation.read")
    async def read(self) -> list[Automatism]:
        """Every automation, opening a panel session only if the read needs one.

        May raise the session errors when it does.
        """
        state = self._state
        return await with_session_if_needed(
            state, lambda: state.client.automation.list(state.system_id)
        )

    @bounded("automation.command")
    async def command(
        self, automatism: Automatism, command: str, *, position: int | None = None
    ) -> None:
        """Send `command` to `automatism`, inside a panel session.

        Refused before anything is sent when the automation does not list the command, or
        when a position comes with any command but POSITION, or POSITION without one: the
        panel is the wrong place to find out, and the app never sends such a payload. That
        refusal is a `DaitemUsageError`. Holds a panel session, so may raise the session
        errors, and is never replayed after a `DaitemConnectionError`.
        """
        if not automatism.accepts(command):
            name = automatism.label or automatism.id
            raise DaitemUsageError(f"{name} does not accept {command}")
        check_position(command, position)
        state = self._state
        async with state.session():
            await state.sending(
                state.client.automation.command(
                    state.system_id, automatism.id, command, position=position
                )
            )
