"""Account and systems: `client.account.*`."""

from __future__ import annotations

from typing import Any

from ..models import Inventory, System
from .transport import _Transport


class _Account:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def get_user(self) -> dict[str, Any]:
        data: dict[str, Any] = await self._transport.request("GET", "/topaze/v1/user")
        return data

    async def list_systems(self) -> list[System]:
        data = await self._transport.request("GET", "/topaze/v5/systems")
        return [System.from_json(item) for item in data]

    async def get_inventory(self, system_id: int) -> Inventory:
        """Device inventory. Does not include live open/closed detector state."""
        data = await self._transport.request("GET", f"/topaze/v2/systems/{system_id}/configuration")
        return Inventory.from_json(data)
