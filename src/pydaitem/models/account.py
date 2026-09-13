"""An installation the signed-in account can access: `System`."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class System:
    """An installation the signed-in account can access."""

    id: int
    name: str
    role: int
    vendor: str = ""

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> System:
        return cls(
            id=data["id"],
            name=data.get("name") or "",
            role=data.get("role", 0),
            vendor=data.get("vendor") or "",
        )

    @property
    def is_owner(self) -> bool:
        """role 1 is owner, role 0 is a restricted user."""
        return self.role == 1
