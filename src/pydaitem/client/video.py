"""Cameras and recorded clips: `client.video.*`.

Live video is not reachable through this API: the app plays it through the camera vendor's
own SDK. Recorded clips are, with the same token as every other call.
"""

from __future__ import annotations

import re
from typing import Any

from ..const.devices import ClipCategory
from ..models import Camera, Clip
from ..models._shared import dicts, parse
from . import jobs
from .paths import segment
from .transport import _Transport

#: Shape of a capture job path, enforced like the logbook's.
_CAPTURE_JOB_RE = re.compile(
    rf"/topaze/v5/systems/\d+/videos/capture/carir/{jobs.JOB_ID}/{jobs.JOB_ID}"
)

#: How long to wait for a capture, and how often to poll it meanwhile.
CAPTURE_POLL_TIMEOUT = 60.0
CAPTURE_POLL_INTERVAL = 2.0


class _Video:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def list_cameras(self, system_id: int) -> list[Camera]:
        data = await self._transport.request("GET", f"/topaze/v1/systems/{system_id}/cameras")
        return parse(lambda: [Camera.from_json(item) for item in dicts(data, "cameras")], "cameras")

    async def list_clips(self, system_id: int) -> list[Clip]:
        """Recorded clips, on alarm and on demand, newest first as sent."""
        data = await self._transport.request("GET", f"/topaze/v6/systems/{system_id}/videos")
        return parse(lambda: [Clip.from_json(item) for item in dicts(data, "videos")], "clips")

    def clip_path(self, system_id: int, clip: Clip) -> str:
        """Path of a clip's MP4, relative to `api_base`, for a caller that proxies it.

        A clip without a device uid is fetched with `0` in its place, as the app does.
        """
        return f"{_clip_base(system_id, clip)}/mpeg4"

    async def download_clip(self, system_id: int, clip: Clip) -> bytes:
        return await self._transport.request_bytes("GET", self.clip_path(system_id, clip))

    async def delete_clip(self, system_id: int, clip: Clip) -> None:
        """WARNING: deletes the recording for good."""
        await self._transport.request("DELETE", _clip_base(system_id, clip), retry=False)

    async def start_capture(self, system_id: int, carir_id: str) -> str:
        """Ask a capture detector for a clip now, and return the job path to poll.

        The job id is expected in the `Location` header, as for the logbook. A
        `transactionId` in the body is accepted too.
        """
        data, headers = await self._transport.request_full(
            "POST",
            f"/topaze/v5/systems/{system_id}/videos/capture/carir/{segment(carir_id)}",
            retry=False,
        )
        location = headers.get("Location")
        if not location and isinstance(data, dict) and data.get("transactionId"):
            location = (
                f"/v5/systems/{system_id}/videos/capture/carir/{carir_id}/{data['transactionId']}"
            )
        return jobs.job_path(location, _CAPTURE_JOB_RE, "capture job", system_id=system_id)

    async def get_capture(self, job_path: str) -> dict[str, Any]:
        """One poll of a capture job started by `start_capture`."""
        path = jobs.job_path(job_path, _CAPTURE_JOB_RE, "capture job")
        return await self._transport.request_object("GET", path)

    async def capture(self, system_id: int, carir_id: str) -> Any:
        """Start a capture and wait for it. Returns the job's `response` as sent."""
        path = await self.start_capture(system_id, carir_id)
        return await jobs.poll_job(
            self._transport,
            path,
            timeout=CAPTURE_POLL_TIMEOUT,
            interval=CAPTURE_POLL_INTERVAL,
            what="capture",
        )


def _clip_base(system_id: int, clip: Clip) -> str:
    """A clip's path, without the format. One without a device uid takes `0`, as in the app.

    Each segment comes from the server, so it is escaped: a `/` or `..` in it must not move
    the authenticated request (a DELETE among them) to another endpoint.
    """
    category = segment(str(clip.category or ClipCategory.DETECTOR))
    device_uid = segment(clip.device_uid or "0")
    clip_id = segment(clip.id)
    return f"/topaze/v5/systems/{system_id}/videos/{category}/{device_uid}/{clip_id}"
