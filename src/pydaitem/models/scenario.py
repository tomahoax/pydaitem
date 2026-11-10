"""Scenarios: `Scenario`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._shared import dicts


@dataclass(slots=True, kw_only=True)
class Scenario:
    """One scenario, from `GET /v6/systems/<id>/scenarios`.

    A scenario may disarm the alarm among its actions. `actions` is kept raw so a caller can
    check before running it.
    """

    id: int
    name: str = ""
    active: bool = False
    trigger: str = ""
    """`triggerType`: `MANUAL`, `AUTO_FIRE` or `AUTO_INTRUSION`."""
    actions: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Scenario:
        return cls(
            id=int(data.get("id") or 0),
            name=str(data.get("name") or ""),
            active=bool(data.get("active")),
            trigger=str(data.get("triggerType") or ""),
            actions=dicts(data.get("actions")),
            raw=data,
        )
