"""Credential resolution for scripts and command line tools.

A host application that already manages its own credentials has nothing to do with this
module. It exists so scripts stop reimplementing the same env-file parser.

Resolution order, most explicit first: arguments, then environment variables, then an env
file.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from .exceptions import MissingCredentials

_LOGGER = logging.getLogger(__name__)

ENV_EMAIL = "DAITEM_EMAIL"
ENV_PASSWORD = "DAITEM_PASSWORD"
ENV_CODE = "DAITEM_MASTER_CODE"
ENV_SYSTEM_ID = "DAITEM_SYSTEM_ID"


@dataclass(slots=True, kw_only=True)
class Credentials:
    """Everything needed to drive one installation."""

    email: str
    password: str
    code: str
    """Alarm code of the account in use, not necessarily the owner's master code."""
    system_id: int | None = None

    def __repr__(self) -> str:  # pragma: no cover - defensive
        """Never render the secrets, so they cannot leak into a traceback or a log."""
        return f"Credentials(email={self.email!r}, code=***, password=***)"


def read_env_file(path: Path | str) -> dict[str, str]:
    """Parse a simple KEY=VALUE file. Missing file yields an empty mapping.

    Blank lines and `#` comments are skipped, an `export ` prefix is accepted, and one pair
    of matching quotes around a value is removed, no more: a password may start or end with
    a quote character.
    """
    values: dict[str, str] = {}
    file = Path(path).expanduser()
    if not file.exists():
        return values
    try:
        text = file.read_text(encoding="utf-8")
        if file.stat().st_mode & 0o077:
            _LOGGER.warning("The env file %s is readable by other users: chmod 600 it", file)
    except (OSError, UnicodeDecodeError) as err:
        raise MissingCredentials(f"Cannot read the env file {file}: {err}") from err
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def resolve_credentials(
    *,
    email: str | None = None,
    password: str | None = None,
    code: str | None = None,
    system_id: int | None = None,
    env_file: Path | str | None = None,
) -> Credentials:
    """Resolve credentials from arguments, the environment, then an env file.

    Raises `MissingCredentials` naming what is missing, rather than failing later with an
    opaque authentication error.
    """
    from_file = read_env_file(env_file) if env_file else {}

    def pick(explicit: str | None, key: str) -> str | None:
        return explicit or os.environ.get(key) or from_file.get(key) or None

    resolved_email = pick(email, ENV_EMAIL)
    resolved_password = pick(password, ENV_PASSWORD)
    resolved_code = pick(code, ENV_CODE)

    missing = [
        name
        for name, value in (
            (ENV_EMAIL, resolved_email),
            (ENV_PASSWORD, resolved_password),
            (ENV_CODE, resolved_code),
        )
        if not value
    ]
    if missing:
        raise MissingCredentials(f"Missing credential(s): {', '.join(missing)}")

    raw_system = system_id or pick(None, ENV_SYSTEM_ID)
    assert resolved_email and resolved_password and resolved_code  # narrowed above

    try:
        resolved_system = int(raw_system) if raw_system else None
    except ValueError as err:
        raise MissingCredentials(f"{ENV_SYSTEM_ID} must be a number, got {raw_system!r}") from err

    return Credentials(
        email=resolved_email,
        password=resolved_password,
        code=resolved_code,
        system_id=resolved_system,
    )


__all__ = ["Credentials", "MissingCredentials", "resolve_credentials"]
