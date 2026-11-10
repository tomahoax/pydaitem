"""Reads beyond the alarm itself: automations, cameras and clips in one go.

Each read is tried without a panel session first, and a single session is opened for
whatever needs one, the way `client.panel.get_status` reads the state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from ..exceptions import DaitemApiError, DaitemError, DaitemNoSessionError
from ..models import Automatism, Camera, Clip
from ..models._shared import PARSE_ERRORS
from .state import _SystemState


@dataclass(slots=True, kw_only=True)
class Extras:
    """What `DaitemSystem.read_extras` read. A list is None when its read failed."""

    automatisms: list[Automatism] | None = None
    cameras: list[Camera] | None = None
    clips: list[Clip] | None = None
    errors: dict[str, DaitemError] = field(default_factory=dict)
    """Why a read failed, by field name, so a consumer can keep its previous value."""

    @property
    def latest_clip(self) -> Clip | None:
        """The most recent clip with a date, whatever order the API sent them in."""
        dated = [clip for clip in self.clips or [] if clip.taken_at is not None]
        return max(dated, key=lambda clip: clip.taken_at or 0) if dated else None


async def read_extras(state: _SystemState) -> Extras:
    client, system_id = state.client, state.system_id
    results, errors = await read_with_one_session(
        state,
        {
            "automatisms": lambda: client.automation.list(system_id),
            "cameras": lambda: client.video.list_cameras(system_id),
            "clips": lambda: client.video.list_clips(system_id),
        },
    )
    return Extras(errors=errors, **results)


Reader = Callable[[], Awaitable[Any]]
_T = TypeVar("_T")


async def read_with_one_session(
    state: _SystemState, readers: dict[str, Reader]
) -> tuple[dict[str, Any], dict[str, DaitemError]]:
    """Run every reader, opening at most one panel session for those that need it.

    Returns what each successful reader gave and why each other one failed, by name.
    """
    results: dict[str, Any] = {}
    errors: dict[str, DaitemError] = {}
    need_session = await _run(state, readers, results, errors, in_session=False)
    if need_session:
        try:
            # Within the try: a budget run out lands in `errors`, it never escapes.
            async with state.deadline("panel session"), state.session():
                await _run(
                    state,
                    {name: readers[name] for name in need_session},
                    results,
                    errors,
                    in_session=True,
                )
        except DaitemError as err:
            for name in need_session:
                errors.setdefault(name, err)
    return results, errors


async def _run(
    state: _SystemState,
    readers: dict[str, Reader],
    results: dict[str, Any],
    errors: dict[str, DaitemError],
    *,
    in_session: bool,
) -> list[str]:
    """Run each reader, keep its result or its error, and return those that need a session.

    Without a session the readers run at once: they wait on the network, not on each other.
    Inside one they run in turn, so the panel gets one request at a time.
    """

    async def run_one(name: str, read: Reader) -> str | None:
        try:
            async with state.deadline(name):
                results[name] = await read()
            errors.pop(name, None)
        except DaitemNoSessionError as err:
            if not in_session:
                return name
            errors[name] = err
        except DaitemError as err:
            errors[name] = err
        except _PARSE_ERRORS as err:
            # An answer shaped otherwise than expected fails this read only, not the others.
            errors[name] = DaitemApiError(f"{name}: unexpected answer ({err!r})")
        return None

    if in_session:
        outcomes = [await run_one(name, read) for name, read in readers.items()]
    else:
        outcomes = await asyncio.gather(*(run_one(name, read) for name, read in readers.items()))
    return [name for name in outcomes if name is not None]


_PARSE_ERRORS = PARSE_ERRORS


async def with_session_if_needed(state: _SystemState, read: Callable[[], Awaitable[_T]]) -> _T:
    """Run `read`, and once more inside a panel session if it says one is needed.

    An answer the models cannot parse raises `DaitemApiError`, as in `read_with_one_session`.
    """
    try:
        try:
            return await read()
        except DaitemNoSessionError:
            async with state.session():
                return await read()
    except _PARSE_ERRORS as err:
        raise DaitemApiError(f"unexpected answer ({err!r})") from err
