"""One poll cycle in one call: the state and the inventory, each with its own failure."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypeVar

from ..exceptions import DaitemError
from ..models import Inventory, SystemStatus

if TYPE_CHECKING:
    from . import DaitemSystem


@dataclass(slots=True, kw_only=True)
class Snapshot:
    """What `DaitemSystem.read_snapshot` read. A field is None when its read failed."""

    status: SystemStatus | None = None
    inventory: Inventory | None = None
    errors: dict[str, DaitemError] = field(default_factory=dict)
    """Why a read failed, by field name (`status`, `inventory`), so a consumer can keep its
    previous value and act on the error's `remedy`."""


_T = TypeVar("_T")


async def read_snapshot(system: DaitemSystem) -> Snapshot:
    # Both at once: the inventory needs no panel session, so neither waits for the other,
    # and a busy panel does not hide the faults.
    (inventory, inventory_error), (status, status_error) = await asyncio.gather(
        _caught(system.inventory.read()), _caught(system.panel.read())
    )
    snapshot = Snapshot(status=status, inventory=inventory)
    if inventory_error is not None:
        snapshot.errors["inventory"] = inventory_error
    if status_error is not None:
        snapshot.errors["status"] = status_error
    return snapshot


async def _caught(read: Awaitable[_T]) -> tuple[_T | None, DaitemError | None]:
    """What `read` gave, or the `DaitemError` it raised: anything else still propagates."""
    try:
        return await read, None
    except DaitemError as err:
        return None, err
