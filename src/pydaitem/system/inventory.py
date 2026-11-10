"""Device inventory and faults: `system.inventory.*`."""

from __future__ import annotations

from ..models import Inventory
from .state import _SystemState, bounded


class _Inventory:
    def __init__(self, state: _SystemState) -> None:
        self._state = state

    @bounded("inventory.read")
    async def read(self, *, max_age: float = 0.0) -> Inventory:
        """Read the device inventory, including current faults and firmware versions.

        Needs no panel session, so it is safe to call on every poll cycle. Faults live
        here, so refreshing it is what keeps fault reporting alive. Never raises a session
        error.
        """
        state = self._state
        kept: Inventory | None = state.kept("inventory.read", max_age)
        if kept is not None:
            return kept
        inventory = await state.shared(
            "inventory.read", lambda: state.client.account.get_inventory(state.system_id)
        )
        state.keep("inventory.read", inventory)
        return inventory
