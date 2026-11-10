"""Recurring arm/disarm programs: `client.schedule.*`.

Works on raw `dict[str, Any]` payloads, like the API itself; the conversion to
`Schedule`/`ScheduleProgram` lives in `DaitemSystem`.
"""

from __future__ import annotations

from typing import Any

from .paths import segment
from .transport import _Transport


class _Schedule:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def get(self, system_id: int) -> dict[str, Any]:
        """Raw schedule: `{globalActivation, programs, maxProgramCount}`."""
        return await self._transport.request_object(
            "GET", f"/topaze/v5/systems/{system_id}/schedule"
        )

    async def add_program(self, system_id: int, program: dict[str, Any]) -> dict[str, Any]:
        """Add a program: `{day, hour, minute, command, groups}`, `id` as the app sends it.

        WARNING: changes when the alarm arms and disarms itself.
        """
        return await self._transport.request_object(
            "POST", f"/topaze/v5/systems/{system_id}/schedule", json=program, retry=False
        )

    async def update_program(self, system_id: int, program: dict[str, Any]) -> dict[str, Any]:
        """Update an existing program. `program["id"]` must already exist."""
        program_id = program["id"]
        return await self._transport.request_object(
            "PUT",
            f"/topaze/v5/systems/{system_id}/schedule/{segment(program_id)}",
            json=program,
            retry=False,
        )

    async def delete_program(self, system_id: int, program_id: int) -> None:
        await self._transport.request(
            "DELETE", f"/topaze/v5/systems/{system_id}/schedule/{segment(program_id)}", retry=False
        )

    async def set_active(self, system_id: int, active: bool) -> None:
        """Master switch for the whole schedule, independent of each program."""
        await self._transport.request(
            "PUT",
            f"/topaze/v5/systems/{system_id}/schedule/activate",
            json={"activate": active},
            retry=False,
        )
