"""URL path segments built from values, so a value cannot change which endpoint is called."""

from __future__ import annotations

from urllib.parse import quote

from ..exceptions import DaitemUsageError


def segment(value: object) -> str:
    """`value` as one path segment: an integer as it is, anything else escaped.

    A slash, `..` or `?` in an id from the server or from a caller would otherwise move an
    authenticated request, a command or a deletion among them, to another endpoint.
    """
    if isinstance(value, bool):
        raise DaitemUsageError(f"not a usable path segment: {value!r}")
    if isinstance(value, int):
        return str(value)
    text = str(value)
    if text in {"", ".", ".."}:
        raise DaitemUsageError(f"not a usable path segment: {value!r}")
    return quote(text, safe="")
