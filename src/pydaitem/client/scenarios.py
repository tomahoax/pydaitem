"""Scenarios: `client.scenarios.*`. Running one is `client.commands.start_scenario`.

WARNING: a scenario may disarm the alarm among its actions. `create`, `update` and
`delete` change what the installation does.
"""

from __future__ import annotations

from typing import Any

from ..models import Scenario
from ..models._shared import dicts, parse
from .paths import segment
from .transport import _Transport


class _Scenarios:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def list(self, system_id: int) -> list[Scenario]:
        data = await self._transport.request("GET", f"/topaze/v6/systems/{system_id}/scenarios")
        return parse(
            lambda: [Scenario.from_json(item) for item in dicts(data, "scenarios")], "scenarios"
        )

    async def create(self, system_id: int, scenario: dict[str, Any]) -> dict[str, Any]:
        """`scenario` is `{name, active, triggerType, actions}` as `templates()` shows them."""
        return await self._transport.request_object(
            "POST", f"/topaze/v6/systems/{system_id}/scenarios", json=scenario, retry=False
        )

    async def update(self, system_id: int, scenario: dict[str, Any]) -> dict[str, Any]:
        """Replace a scenario whole (`scenario["id"]` must exist), for instance to toggle it."""
        scenario_id = scenario["id"]
        return await self._transport.request_object(
            "PUT",
            f"/topaze/v6/systems/{system_id}/scenarios/{segment(scenario_id)}",
            json=scenario,
            retry=False,
        )

    async def delete(self, system_id: int, scenario_id: int) -> None:
        await self._transport.request(
            "DELETE",
            f"/topaze/v6/systems/{system_id}/scenarios/{segment(scenario_id)}",
            retry=False,
        )

    async def templates(self, system_id: int) -> dict[str, Any]:
        return await self._transport.request_object(
            "GET", f"/topaze/v6/systems/{system_id}/scenarios/templates"
        )

    async def actions(self, system_id: int) -> dict[str, Any]:
        """Actions a scenario may use, the alarm commands among them."""
        return await self._transport.request_object(
            "GET", f"/topaze/v6/systems/{system_id}/scenarios/actions"
        )

    async def configuration(self, system_id: int) -> dict[str, Any]:
        """Limits: triggers, how many scenarios each allows, and the delay range."""
        return await self._transport.request_object(
            "GET", f"/topaze/v5/systems/{system_id}/scenarios/configuration"
        )
