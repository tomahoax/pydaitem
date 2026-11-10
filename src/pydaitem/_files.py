"""Writing a file that holds a secret or personal data."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

#: Owner read/write only.
PRIVATE_MODE = 0o600


def write_private(path: Path, text: str) -> None:
    """Write `text` to `path`, readable by its owner only, and atomically.

    The content goes to a temporary file whose mode is set before anything is written, then
    replaces `path`, so an interrupted write never leaves a truncated file behind and the
    content is never readable by others, even briefly. Raises `OSError`.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-")
    tmp = Path(tmp_name)
    try:
        # fdopen first, so the descriptor is closed whatever fails next.
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), PRIVATE_MODE)
            handle.write(text)
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
