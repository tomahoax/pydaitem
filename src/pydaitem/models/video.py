"""Cameras and recorded clips: `Camera`, `Clip`.

Live video goes through the camera vendor's own SDK and is not reachable here; recorded
clips are, through `client.video`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ._shared import text

#: Timestamps above this are taken as milliseconds, below it as seconds.
_MS_THRESHOLD = 10**11


@dataclass(slots=True, kw_only=True)
class Camera:
    """One camera, from `GET /v1/systems/<id>/cameras`.

    The vendor connection details (`dahuaInfo`, `dahuaCloudInfo`) are left in `raw` only:
    they are credentials for the vendor's cloud, not something to display or log.
    """

    id: int
    uid: str = ""
    type: str = ""
    """`CameraType` value, or the raw value when unknown."""
    name: str = ""
    model: str = ""
    status: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Camera:
        return cls(
            id=int(data.get("id") or 0),
            uid=str(data.get("uid") or ""),
            type=str(data.get("type") or ""),
            name=str(data.get("name") or ""),
            model=str(data.get("model") or ""),
            status=str(data["status"]) if data.get("status") is not None else None,
            raw=data,
        )


@dataclass(slots=True, kw_only=True)
class Clip:
    """One recorded clip, from `GET /v6/systems/<id>/videos`."""

    id: str
    taken_at: datetime | None = None
    """From `timestamp`, read as seconds or milliseconds since the epoch, in UTC."""
    duration_ms: int | None = None
    format: str | None = None
    """`ClipFormat` value."""
    kind: str | None = None
    """`ClipKind` value: recorded on alarm, or on demand."""
    category: str | None = None
    """`ClipCategory` value, also the device type in the download path."""
    device_uid: str | None = None
    carir: str | None = None
    """Capture detector the clip comes from, when it is one."""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Clip:
        return cls(
            id=str(data.get("id") or ""),
            taken_at=_timestamp(data.get("timestamp")),
            duration_ms=data.get("durationMs") if isinstance(data.get("durationMs"), int) else None,
            format=text(data.get("format")),
            kind=text(data.get("type")),
            category=text(data.get("category")),
            device_uid=text(data.get("deviceUid")),
            carir=text(data.get("carir")),
            raw=data,
        )


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, int | float) or value <= 0:
        return None
    seconds = value / 1000 if value > _MS_THRESHOLD else value
    try:
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None
