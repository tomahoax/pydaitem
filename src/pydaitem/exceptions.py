"""pydaitem exceptions.

The hierarchy mirrors conditions actually met on the API, so consumers can react
precisely instead of catching a generic error.
"""

from __future__ import annotations


class DaitemError(Exception):
    """Generic pydaitem error."""


class MissingCredentials(DaitemError):
    """A required credential could not be resolved.

    Raised by `resolve_credentials`, before any request is made — a usage error, not a
    condition the API itself returns, but still part of the `DaitemError` hierarchy so
    consumers have exactly one base class to catch.
    """


class DaitemAuthError(DaitemError):
    """Authentication failed: bad credentials, or the Keycloak flow changed."""


class DaitemConnectionError(DaitemError):
    """Network or transport failure (DNS, TLS, dropped socket, timeout)."""


class DaitemForbiddenError(DaitemError):
    """403: the account lacks rights for this resource.

    Known cases, both owner-only: reading the logbook, and the schedule endpoints
    (confirmed live: a restricted account gets a 403 reading `/schedule`).
    """


class DaitemSessionBusyError(DaitemError):
    """409: another device already holds the panel session.

    The panel accepts a single session at a time, across all accounts, so a secondary
    account does not work around it. The caller should retry later.
    """

    def __init__(self, holder: str | None = None) -> None:
        self.holder = holder
        detail = f" (held by: {holder})" if holder else ""
        super().__init__(f"Panel session already open{detail}")


class DaitemNoSessionError(DaitemError):
    """500: no usable session on the panel, either missing or stale.

    Reading the state requires a session opened by any device. The caller should call
    `connect()` and retry.
    """


class DaitemCommandError(DaitemError):
    """The panel rejected the command or did not confirm it (`commandStatus` != CMD_OK)."""
