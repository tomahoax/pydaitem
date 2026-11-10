"""Helpers shared by more than one model module."""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import cache
from typing import Any, TypeVar

from ..exceptions import DaitemApiError

_LOGGER = logging.getLogger("pydaitem.models")

_T = TypeVar("_T")

#: What a model raises on an answer shaped otherwise than expected.
PARSE_ERRORS = (AttributeError, KeyError, TypeError, ValueError)


def parse(build: Callable[[], _T], what: str) -> _T:
    """Run `build`, a model built from an API answer, turning a shape surprise into
    `DaitemApiError` so it stays within the library's errors.
    """
    try:
        return build()
    except PARSE_ERRORS as err:
        raise DaitemApiError(f"{what}: unexpected answer ({err!r})") from err


def int_id(value: Any) -> int:
    """An id the API sends as a number, refused when it is anything else."""
    if isinstance(value, bool):
        raise ValueError(f"not an id: {value!r}")
    return int(value)


@cache
def _warn_unknown(kind: str, value: str) -> None:
    """Log an unmapped API value once, so a change surfaces instead of vanishing."""
    _LOGGER.warning(
        "Unknown %s %r returned by the Daitem API. pydaitem may need updating; "
        "please report it with the raw value.",
        kind,
        value,
    )


def dicts(value: Any, key: str | None = None) -> list[dict[str, Any]]:
    """The objects of a JSON list, dropping anything else.

    With `key`, an object holding that list under `key` is accepted too, since the API wraps
    some lists (`{"cameras": [...]}`) and not others. Anything that is not a list yields `[]`.
    """
    if key is not None and isinstance(value, dict):
        value = value.get(key)
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def find_key(data: Any, key: str) -> Any:
    """First truthy value of `key` anywhere in a JSON document, whatever its nesting."""
    if isinstance(data, dict):
        if data.get(key):
            return data[key]
        values = list(data.values())
    elif isinstance(data, list):
        values = data
    else:
        return None
    for value in values:
        found = find_key(value, key)
        if found:
            return found
    return None


def text(value: Any) -> str | None:
    """`value` as a string, or None when it is absent or empty."""
    return str(value) if value is not None and value != "" else None
