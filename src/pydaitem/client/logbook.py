"""Event history job: `client.logbook.*`."""

from __future__ import annotations

import re
from typing import Any

from ..models._shared import dicts
from . import jobs
from .transport import _Transport

#: How long to wait for the event log, and how often to poll it meanwhile.
LOGBOOK_POLL_TIMEOUT = 60.0
LOGBOOK_POLL_INTERVAL = 2.0

#: Shape of a logbook job path, enforced like the other jobs'.
_JOB_PATH_RE = re.compile(rf"/topaze/v5/systems/\d+/logbook/{jobs.JOB_ID}")


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
        return jobs.job_path(
            headers.get("Location"), _JOB_PATH_RE, "logbook job", system_id=system_id
        )

    async def get_job(self, job_path: str) -> dict[str, Any]:
        """One poll of a logbook job created by `create_job`.

        Rejects anything not shaped like a job path, so an unexpected `job_path` cannot
        make the authenticated request land on a different endpoint.
        """
        path = jobs.job_path(job_path, _JOB_PATH_RE, "logbook job")
        return await self._transport.request_object("GET", path)

    async def wait_job(self, job_path: str) -> list[dict[str, Any]]:
        """Poll a job created by `create_job` until it is done: the entries, newest first."""
        path = jobs.job_path(job_path, _JOB_PATH_RE, "logbook job")
        response = await jobs.poll_job(
            self._transport,
            path,
            timeout=LOGBOOK_POLL_TIMEOUT,
            interval=LOGBOOK_POLL_INTERVAL,
            what="logbook",
        )
        return dicts(response)

    async def read(self, system_id: int) -> list[dict[str, Any]]:
        """Create the job and wait for it: the event log, newest first as sent."""
        return await self.wait_job(await self.create_job(system_id))
