"""Business error messages returned by Topaze, used to type exceptions."""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ServerMessage(StrEnum):
    """Business error messages returned by Topaze, used to type exceptions."""

    SESSION_ALREADY_OPEN = "transmitter.connection.sessionalreadyopen"
    """409: another device already holds the panel session."""
    NO_TTM_SESSION = "status.nottmsessionid"
    """500: no session open, `connect` is required first."""
    INVALID_SESSION = "transmitter.error.invalidsessionid"
    """500: a session exists but its id is stale. Same remedy: `connect`."""
    UNEXPECTED = "unexpected.error"
    """500: generic. Sometimes a session error in disguise, see NO_SESSION_DETAIL."""


#: Some endpoints report a missing session as a generic `unexpected.error` whose `details`
#: carries the real cause. Matching on that text is a heuristic, but it is the only signal
#: the API gives, and treating it as a session error is strictly better than a generic
#: failure since the remedy is the same.
NO_SESSION_DETAIL: Final = "TTM session not found"
