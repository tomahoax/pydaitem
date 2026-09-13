"""Recurring arm/disarm programs: `client.schedule.*`.

Works on raw `dict[str, Any]` payloads, like the API itself; the conversion to
`Schedule`/`ScheduleProgram` lives in `DaitemSystem`.
"""

from __future__ import annotations

from typing import Any

from .transport import _Transport


class _Schedule:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def get(self, system_id: int) -> dict[str, Any]:
        """Raw schedule: `{globalActivation, programs, maxProgramCount}`."""
        data: dict[str, Any] = await self._transport.request(
            "GET", f"/topaze/v5/systems/{system_id}/schedule"
        )
        return data

    async def update_program(self, system_id: int, program: dict[str, Any]) -> dict[str, Any]:
        """Update an existing program. `program["id"]` must already exist.

        Creating a new program (a `POST`) has never been observed on the live API and is
        not implemented here, see the README.
        """
        program_id = program["id"]
        data: dict[str, Any] = await self._transport.request(
            "PUT", f"/topaze/v5/systems/{system_id}/schedule/{program_id}", json=program
        )
        return data

    async def delete_program(self, system_id: int, program_id: int) -> None:
        await self._transport.request(
            "DELETE", f"/topaze/v5/systems/{system_id}/schedule/{program_id}"
        )

    async def set_active(self, system_id: int, active: bool) -> None:
        """Master switch for the whole schedule, independent of each program."""
        await self._transport.request(
            "PUT", f"/topaze/v5/systems/{system_id}/schedule/activate", json={"activate": active}
        )
