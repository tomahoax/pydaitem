"""Helpers shared by more than one model module."""

from __future__ import annotations

import logging
from functools import cache

_LOGGER = logging.getLogger("pydaitem.models")


@cache
def _warn_unknown(kind: str, value: str) -> None:
    """Log an unmapped API value once, so a change surfaces instead of vanishing."""
    _LOGGER.warning(
        "Unknown %s %r returned by the Daitem API. pydaitem may need updating; "
        "please report it with the raw value.",
        kind,
        value,
    )
