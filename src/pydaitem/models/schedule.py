"""Recurring arm/disarm programs: `ScheduleProgram`, `Schedule`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ScheduleProgram:
    """One recurring arm/disarm program.

    Creating a new program was never observed on the live API and is not supported: only
    an existing `id` can be updated. See `client.schedule.update_program`.
    """

    id: int
    day: str
    """"monday" through "sunday"."""
    hour: int
    minute: int
    command: bool
    """True arms, False disarms."""
    groups: list[int] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ScheduleProgram:
        return cls(
            id=data.get("id", 0),
            day=data.get("day") or "",
            hour=data.get("hour", 0),
            minute=data.get("minute", 0),
            command=bool(data.get("command")),
            groups=list(data.get("groups") or []),
            raw=data,
        )

    def to_json(self) -> dict[str, Any]:
        """Payload for `client.schedule.update_program`."""
        return {
            "id": self.id,
            "day": self.day,
            "hour": self.hour,
            "minute": self.minute,
            "command": self.command,
            "groups": self.groups,
        }


@dataclass(slots=True)
class Schedule:
    """The installation's full recurring arm/disarm schedule, from `/v5/systems/<id>/schedule`."""

    global_activation: bool = False
    """Master switch for the whole schedule, independent of each program."""
    programs: list[ScheduleProgram] = field(default_factory=list)
    max_program_count: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Schedule:
        return cls(
            global_activation=bool(data.get("globalActivation")),
            programs=[ScheduleProgram.from_json(p) for p in data.get("programs") or []],
            max_program_count=data.get("maxProgramCount", 0),
            raw=data,
        )
