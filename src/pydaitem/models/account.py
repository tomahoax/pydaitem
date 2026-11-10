"""An installation the signed-in account can access: `System`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._shared import int_id


@dataclass(slots=True, kw_only=True)
class System:
    """An installation the signed-in account can access."""

    id: int
    name: str
    role: int
    vendor: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> System:
        return cls(
            id=int_id(data["id"]),
            name=data.get("name") or "",
            role=int(data.get("role") or 0),
            vendor=data.get("vendor") or "",
            raw=data,
        )

    @property
    def is_owner(self) -> bool:
        """role 1 is owner, role 0 is a restricted user."""
        return self.role == 1
