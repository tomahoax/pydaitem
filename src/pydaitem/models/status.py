"""Overall panel/group state: `Group`, `SystemStatus`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..const import ARMED_PANEL_STATES, RAW_TO_PANEL_STATE, PanelState
from ._shared import _warn_unknown


@dataclass(slots=True)
class Group:
    """An alarm group (zone)."""

    id: int
    active: bool
    name: str | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Group:
        return cls(id=data["id"], active=bool(data.get("active")), name=data.get("name"))


def _parse_groups(data: dict[str, Any]) -> list[Group]:
    """Read the groups, tolerating the two shapes the API uses.

    `/state` and command responses put full objects in `groups`. The `connect` response
    instead puts the **active group ids** there as bare integers, with the full objects in
    `groupList`. Both are normalised to `Group` here so callers never see the difference.
    """
    raw = data.get("groups") or []
    if raw and all(isinstance(item, int) for item in raw):
        active_ids = set(raw)
        catalogue = data.get("groupList") or []
        if catalogue:
            return [
                Group(id=g["id"], active=g["id"] in active_ids, name=g.get("name"))
                for g in catalogue
                if isinstance(g, dict) and "id" in g
            ]
        return [Group(id=gid, active=True) for gid in raw]

    return [Group.from_json(g) for g in raw if isinstance(g, dict)]


@dataclass(slots=True)
class SystemStatus:
    """Overall system state, returned by `/state` and by commands."""

    state: str
    groups: list[Group] = field(default_factory=list)
    command_status: str | None = None
    opened_issue_numbers: list[Any] = field(default_factory=list)
    defaults: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> SystemStatus:
        return cls(
            state=data.get("systemState", ""),
            groups=_parse_groups(data),
            command_status=data.get("commandStatus"),
            opened_issue_numbers=data.get("openedIssueNumbers") or [],
            defaults=data.get("defaults"),
            raw=data,
        )

    @property
    def panel_state(self) -> PanelState:
        """Semantic state. Use this, not `state`.

        An unmapped raw value yields `UNKNOWN` and warns once rather than failing or
        silently reading as "no state".
        """
        mapped = RAW_TO_PANEL_STATE.get(self.state)
        if mapped is None:
            _warn_unknown("system state", self.state)
            return PanelState.UNKNOWN
        return mapped

    @property
    def is_armed(self) -> bool:
        return self.panel_state in ARMED_PANEL_STATES

    @property
    def is_arming(self) -> bool:
        """A delay is running: the state will change on its own, keep polling."""
        return self.panel_state is PanelState.ARMING

    @property
    def active_groups(self) -> list[int]:
        return [g.id for g in self.groups if g.active]
