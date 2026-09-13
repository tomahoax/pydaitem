"""Refresh token persistence.

Without a store, every process start replays the full Keycloak login form. Persisting the
refresh token lets a later run resume the session instead, which is faster and avoids
hammering the login endpoint.

The store is a protocol rather than a hardcoded file path, because consumers keep tokens in
different places: a script wants a file, another host application wants its own storage.

The protocol is **async on purpose**: a synchronous file write would block the event loop
for every other coroutine sharing it.

Only the refresh token is persisted. The access token lives 30 minutes and is not worth
storing.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

_LOGGER = logging.getLogger(__name__)

#: Owner read/write only. The refresh token is a credential at rest.
_FILE_MODE = 0o600


@runtime_checkable
class TokenStore(Protocol):
    """Where a client reads and writes its refresh token."""

    async def load(self) -> str | None:
        """Return the stored refresh token, or None if there is none."""

    async def save(self, refresh_token: str | None) -> None:
        """Store a refresh token, or clear the store when given None."""


class FileTokenStore:
    """Store the refresh token in a JSON file, for scripts and command line tools.

    Does real disk I/O, so it belongs outside an event loop that forbids blocking calls.
    """

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path).expanduser()

    async def load(self) -> str | None:
        return await asyncio.to_thread(self._load)

    async def save(self, refresh_token: str | None) -> None:
        await asyncio.to_thread(self._save, refresh_token)

    def _load(self) -> str | None:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as err:
            # A damaged store must not break authentication: fall back to a full login.
            _LOGGER.warning("Ignoring unreadable token store %s: %s", self._path, err)
            return None
        token = data.get("refresh_token")
        return token if isinstance(token, str) and token else None

    def _save(self, refresh_token: str | None) -> None:
        if refresh_token is None:
            self._path.unlink(missing_ok=True)
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"refresh_token": refresh_token}, indent=2) + "\n"

        # Write to a temporary file then rename, so an interrupted write never leaves a
        # truncated store behind. The mode is set before the content is written.
        fd, tmp_name = tempfile.mkstemp(dir=self._path.parent, prefix=".token-")
        tmp = Path(tmp_name)
        try:
            os.fchmod(fd, _FILE_MODE)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            tmp.replace(self._path)
        except OSError as err:
            tmp.unlink(missing_ok=True)
            _LOGGER.warning("Could not persist the refresh token to %s: %s", self._path, err)


class MemoryTokenStore:
    """In-process store. Useful in tests, and as an explicit "no persistence" choice."""

    def __init__(self, refresh_token: str | None = None) -> None:
        self._token = refresh_token

    async def load(self) -> str | None:
        return self._token

    async def save(self, refresh_token: str | None) -> None:
        self._token = refresh_token


__all__ = ["FileTokenStore", "MemoryTokenStore", "TokenStore"]
