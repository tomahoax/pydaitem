"""Event history job: `client.logbook.*`."""

from __future__ import annotations

import re
from typing import Any

from ..exceptions import DaitemError
from .transport import _Transport

#: Shape returned by `create_job`. Enforced in `get_job` so a caller-supplied path cannot
#: redirect the authenticated request to an arbitrary endpoint on `api_base`.
_JOB_PATH_RE = re.compile(r"/topaze/v5/systems/\d+/logbook/[^/]+")


class _Logbook:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def create_job(self, system_id: int) -> str:
        """Request the event history and return the job path to poll.

        The job id only exists in the `Location` header, hence the dedicated method rather
        than leaking transport details into the parsed payload.
        """
        _, headers = await self._transport.request_full(
            "POST", f"/topaze/v5/systems/{system_id}/logbook"
        )
        location = headers.get("Location")
        if not location:
            raise DaitemError("logbook job created without a Location header")
        return location if location.startswith("/topaze") else f"/topaze{location}"

    async def get_job(self, job_path: str) -> dict[str, Any]:
        """Poll a logbook job created by `create_job`.

        Rejects anything not shaped like a job path, so an unexpected `job_path` cannot
        make the authenticated request land on a different endpoint.
        """
        if not _JOB_PATH_RE.fullmatch(job_path):
            raise DaitemError(f"not a logbook job path: {job_path!r}")
        data: dict[str, Any] = await self._transport.request("GET", job_path)
        return data
