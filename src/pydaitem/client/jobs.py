"""Asynchronous jobs: answers the panel gives later, polled until they are done.

A deferred `connect`, a video capture and the logbook all work the same way: the first call
returns a job path (in the `Location` header, relative to `/topaze`), and polling it answers
`{status, response, error}` until `status` is done. The logbook spells the status
`request_status_pending`, the app's enum says `PENDING`, so it is matched loosely.
"""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

from ..exceptions import DaitemApiError, DaitemConnectionError
from .transport import _Transport, api_error

#: One id segment of a job path, for the patterns of `job_path`: no `.` or `..` segment, and no
#: escape, query or fragment that would let the path name another endpoint.
JOB_ID = r"(?!\.\.?(?:/|$))[^/?#%]+"


#: How far the wait between two polls of a job may grow, as a multiple of its first one.
POLL_GROWTH_CAP = 4


class _JobTimeout(DaitemConnectionError):
    """The job was still pending when the caller stopped waiting."""


def job_path(
    location: str | None, pattern: re.Pattern[str], what: str, *, system_id: int | None = None
) -> str:
    """The poll path from a `Location` header, checked against the shape it must have.

    Enforced so a header cannot redirect the authenticated request to an arbitrary endpoint
    on `api_base`. With `system_id`, the path must also belong to that installation.
    """
    if not location:
        raise DaitemApiError(f"{what} started without a Location header")
    path = location if location.startswith("/topaze") else f"/topaze{location}"
    if not pattern.fullmatch(path):
        raise DaitemApiError(f"not a {what} path: {location!r}")
    if system_id is not None and not path.startswith(f"/topaze/v5/systems/{system_id}/"):
        raise DaitemApiError(f"{what} path names another installation: {location!r}")
    return path


async def poll_job(
    transport: _Transport, path: str, *, timeout: float, interval: float, what: str
) -> Any:
    """Poll `path` until the job is done and return its `response`.

    Raises the typed error the job reports, `DaitemApiError` when it ends otherwise (error
    without a message, not found, timed out on the server, an answer of another shape), and
    `_JobTimeout` when it is still pending after `timeout` seconds. Each poll, retries
    included, is cut short at that deadline too.

    The wait between polls doubles from `interval` up to four times it: a job that answers
    quickly is seen quickly, and one that takes long is not asked every second meanwhile.
    """
    deadline = time.monotonic() + timeout
    longest = interval * POLL_GROWTH_CAP
    while True:
        try:
            async with asyncio.timeout_at(_loop_time(deadline)):
                poll = await transport.request("GET", path)
        except TimeoutError:
            raise _JobTimeout(f"{what} still pending after {timeout:g} s") from None
        if not isinstance(poll, dict):
            raise DaitemApiError(f"GET {path}: {what} answered {type(poll).__name__}, not a job")
        status = str(poll.get("status") or "").lower()
        error = poll.get("error")
        if isinstance(error, dict) and error.get("message"):
            raise api_error("GET", path, 200, error.get("message"), error.get("details"))
        if error:
            raise DaitemApiError(f"GET {path}: {what} failed: {error!r}")
        response = poll.get("response")
        if status.endswith("done") or (not status and response is not None):
            return response
        if not status.endswith("pending"):
            raise DaitemApiError(
                f"GET {path}: {what} ended with status {poll.get('status')!r}",
                server_message=str(poll.get("status") or "") or None,
            )
        if time.monotonic() >= deadline:
            raise _JobTimeout(f"{what} still pending after {timeout:g} s")
        await asyncio.sleep(min(interval, max(deadline - time.monotonic(), 0.0)))
        interval = min(interval * 2, longest)


def _loop_time(deadline: float) -> float:
    """`deadline`, a `time.monotonic()` value, on the running loop's clock."""
    loop = asyncio.get_running_loop()
    return loop.time() + (deadline - time.monotonic())
