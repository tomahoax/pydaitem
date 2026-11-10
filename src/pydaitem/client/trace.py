"""What ties the debug lines of one panel session together.

A panel session spans several requests: connect, the reads or the command, and the release,
the latter sometimes in a task of its own. Each line logged while it is open ends with
`[session <id>]`, so one cycle reads as a whole even when several interleave in a log.
The id is drawn locally and never sent: it is not the API's `ttmSessionId`.
"""

from __future__ import annotations

import secrets
import time
from contextvars import ContextVar, Token

_SESSION: ContextVar[str | None] = ContextVar("pydaitem_panel_session", default=None)


def begin() -> tuple[str, Token[str | None]]:
    """Open a trace for a panel session: its id, and what `end` needs."""
    trace_id = secrets.token_hex(2)
    return trace_id, _SESSION.set(trace_id)


def end(token: Token[str | None]) -> None:
    try:
        _SESSION.reset(token)
    except ValueError:
        # Closed from another context (a generator finalised late): just clear it there.
        _SESSION.set(None)


def suffix() -> str:
    """` [session <id>]` while a panel session is open in this task, else nothing."""
    trace_id = _SESSION.get()
    return f" [session {trace_id}]" if trace_id else ""


def elapsed_ms(started: float) -> int:
    """Milliseconds since `started`, a `time.monotonic()` value."""
    return round((time.monotonic() - started) * 1000)
