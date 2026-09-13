"""Output formatting and the confirmation prompt, shared by every command."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from typing import Any


def _confirm(prompt: str, assume_yes: bool) -> bool:
    """Ask before an action that drives the alarm, directly or by changing when it will.

    Without a terminal and without --yes we refuse rather than proceed: a scheduled job
    must state its intent explicitly, and silently arming a house (or changing when it
    will) because nobody could answer a prompt is the wrong default.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(
            "Refusing to proceed without a terminal to confirm on. Pass --yes to "
            "confirm explicitly, for instance from a scheduled job.",
            file=sys.stderr,
        )
        return False
    return input(f"{prompt} [y/N] ").strip().lower() in {"y", "yes"}


def _emit(payload: dict[str, Any], lines: Sequence[str], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for line in lines:
            print(line)
