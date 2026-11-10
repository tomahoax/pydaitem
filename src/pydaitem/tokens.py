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
from pathlib import Path
from typing import Protocol, runtime_checkable

from ._files import write_private

_LOGGER = logging.getLogger(__name__)


@runtime_checkable
class TokenStore(Protocol):
    """Where a client reads and writes its refresh token."""

    async def load(self) -> str | None:
        """Return the stored refresh token, or None if there is none."""

    async def save(self, refresh_token: str | None) -> None:
        """Store a refresh token, or clear the store when given None."""


class FileTokenStore:
    """Store the refresh token in a JSON file, for scripts and command line tools.

    The disk I/O runs in a worker thread, so it does not block the event loop.

    With `account`, the file records which account the token belongs to, and a file saved
    for another account (or before accounts were recorded) is ignored: resuming it would
    drive that other account's alarm. A file owned by another user is ignored too, and one
    readable by others is used with a warning.
    """

    def __init__(self, path: Path | str, *, account: str | None = None) -> None:
        self._path = Path(path).expanduser()
        self._account = account.casefold() if account else None

    async def load(self) -> str | None:
        return await asyncio.to_thread(self._load)

    async def save(self, refresh_token: str | None) -> None:
        await asyncio.to_thread(self._save, refresh_token)

    def _load(self) -> str | None:
        try:
            if not self._trusted():
                return None
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as err:
            # A damaged store must not break authentication: fall back to a full login.
            _LOGGER.warning("Ignoring unreadable token store %s: %s", self._path, err)
            return None
        if not isinstance(data, dict):
            _LOGGER.warning("Ignoring token store %s: not a JSON object", self._path)
            return None
        if self._account is not None and data.get("account") != self._account:
            _LOGGER.info("Ignoring token store %s: saved for another account", self._path)
            return None
        token = data.get("refresh_token")
        return token if isinstance(token, str) and token else None

    def _trusted(self) -> bool:
        """Whether the file may be used: it must belong to the current user."""
        info = self._path.stat()
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            _LOGGER.warning("Ignoring token store %s: owned by another user", self._path)
            return False
        if info.st_mode & 0o077:
            _LOGGER.warning("Token store %s is readable by other users", self._path)
        return True

    def _save(self, refresh_token: str | None) -> None:
        if refresh_token is None:
            try:
                self._path.unlink(missing_ok=True)
            except OSError as err:
                _LOGGER.warning("Could not delete the token store %s: %s", self._path, err)
            return

        content: dict[str, str] = {"refresh_token": refresh_token}
        if self._account is not None:
            content["account"] = self._account
        payload = json.dumps(content, indent=2) + "\n"
        try:
            write_private(self._path, payload)
        except OSError as err:
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
