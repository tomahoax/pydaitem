"""Event log entries: `LogEntry`."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ._shared import dicts


@dataclass(slots=True, kw_only=True)
class LogEntry:
    """One event of the panel history.

    `title` and the messages in `details` are translation keys (`logEvent.36.label2`), which
    the app resolves from its own bundles. They are kept as they are.
    """

    date: str
    """As sent, local time without a zone (`2026-09-07T15:22`)."""
    title: str = ""
    details: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> LogEntry:
        return cls(
            date=str(data.get("date") or ""),
            title=str(data.get("title") or ""),
            details=dicts(data.get("details")),
            raw=data,
        )

    @property
    def when(self) -> datetime | None:
        """`date` as a naive local datetime, or None if it does not parse."""
        try:
            return datetime.fromisoformat(self.date)
        except ValueError:
            return None
