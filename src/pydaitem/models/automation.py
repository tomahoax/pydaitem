"""Automations (gates, garage doors, shutters, lights, plugs): `Automatism`.

Parsing is lenient and keeps the payload in `raw`, so a field that turns out different
shows up in diagnostics instead of breaking.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..const.devices import AutomatismCategory, AutomatismStateType


@dataclass(slots=True, kw_only=True)
class Automatism:
    """One automation, from `GET /v5/systems/<id>/automatisms`."""

    id: str
    label: str = ""
    category: str = AutomatismCategory.UNKNOWN
    """One of `AutomatismCategory`, or the raw value when unknown."""
    available_commands: list[str] = field(default_factory=list)
    """What it accepts, `AutomatismCommand` values. Only these may be sent."""
    state: str | None = None
    """`AutomatismStateType` value: ON, OFF or POSITION. None when not reported."""
    position: int | None = None
    """Position when `state` is POSITION, from 0 to 100."""
    mode: str | None = None
    """The command the app treats as this automation's main mode, when given."""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Automatism:
        raw_state = data.get("state")
        state: dict[str, Any] = raw_state if isinstance(raw_state, dict) else {}
        position = state.get("position")
        return cls(
            id=str(data.get("id", "")),
            label=str(data.get("label") or ""),
            category=str(data.get("category") or AutomatismCategory.UNKNOWN),
            available_commands=[str(c) for c in data.get("availableCommands") or []],
            state=str(state["state"]) if state.get("state") is not None else None,
            position=position if isinstance(position, int) else None,
            mode=str(data["mode"]) if data.get("mode") is not None else None,
            raw=data,
        )

    def accepts(self, command: str) -> bool:
        return command in self.available_commands

    @property
    def is_on(self) -> bool | None:
        """True when reported ON, False when OFF, None otherwise (position or unknown)."""
        if self.state == AutomatismStateType.ON:
            return True
        if self.state == AutomatismStateType.OFF:
            return False
        return None
