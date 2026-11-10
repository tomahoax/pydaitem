"""Automations (gates, garage doors, shutters, lights, plugs): `client.automation.*`.

WARNING: `command()` and `widget_command()` drive real equipment, such as a gate.
"""

from __future__ import annotations

from typing import Any

from ..models import Automatism
from ..models._shared import dicts, parse
from .paths import segment
from .transport import _Transport


class _Automation:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def list(self, system_id: int) -> list[Automatism]:
        """Every automation, with the commands it accepts and its current state."""
        data = await self._transport.request("GET", f"/topaze/v5/systems/{system_id}/automatisms")
        return parse(
            lambda: [Automatism.from_json(item) for item in dicts(data, "automatisms")],
            "automations",
        )

    async def command(
        self, system_id: int, automatism_id: str, command: str, *, position: int | None = None
    ) -> dict[str, Any]:
        """Send `command` (an `AutomatismCommand` it lists), with `position` for POSITION.

        Never retried: a replay could open a gate twice.
        """
        payload: dict[str, Any] = {"type": str(command)}
        if position is not None:
            payload["position"] = position
        return await self._transport.request_object(
            "POST",
            f"/topaze/v5/systems/{system_id}/automatisms/{segment(automatism_id)}/command",
            json=payload,
            retry=False,
        )

    async def widget_command(self, system_id: int, item_id: int, command: str) -> dict[str, Any]:
        """Drive an automation through its home screen widget: `on`, `off` or `launch`.

        Some installations expose an automation as a widget item rather than in `list()`.
        `item_id` is the widget item's `id`. Never retried.
        """
        return await self._transport.request_object(
            "POST",
            f"/topaze/v1/action/systems/{system_id}/sendAutomationWidgetCommand",
            json={"command": command, "id": item_id},
            retry=False,
        )
