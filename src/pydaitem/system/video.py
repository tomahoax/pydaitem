"""Cameras and recorded clips: `system.video.*`.

Live video is not reachable: the app plays it through the camera vendor's own SDK.
"""

from __future__ import annotations

from ..models import Camera, Clip
from .extras import with_session_if_needed
from .state import _SystemState, bounded


class _Video:
    """Reads open a panel session only when the API asks for one, and may then raise the
    session errors.
    """

    def __init__(self, state: _SystemState) -> None:
        self._state = state

    @bounded("video.cameras")
    async def cameras(self) -> list[Camera]:
        """Every camera, opening a panel session only if the read needs one."""
        state = self._state
        return await with_session_if_needed(
            state, lambda: state.client.video.list_cameras(state.system_id)
        )

    @bounded("video.clips")
    async def clips(self) -> list[Clip]:
        """Recorded clips, on alarm and on demand, opening a panel session only if needed."""
        state = self._state
        return await with_session_if_needed(
            state, lambda: state.client.video.list_clips(state.system_id)
        )
