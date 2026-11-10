"""pydaitem exceptions.

The hierarchy mirrors conditions actually met on the API, so consumers can react
precisely instead of catching a generic error.

Every exception also carries what a consumer needs without a chain of `isinstance`:

- `remedy`, a `Remedy`: what to do about it. Most classes have one remedy, a few refine it
  case by case (a write whose answer was lost, a sign-in flow that changed).
- `code`, a short stable identifier of the class, for a translated message.
- `placeholders`, the values such a message may show, as strings.

The message itself is technical (method, path, server message) and meant for logs.
"""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any, ClassVar

from .const.errors import CommandStatus


class Remedy(StrEnum):
    """What a consumer should do about a `DaitemError`. **Stable public contract.**

    A member may be added in a minor release: treat one you do not know as `RETRY_LATER`.
    """

    RETRY_LATER = auto()
    """Transient: the same call can succeed later. A busy panel, the network, a rate limit
    (back off), an answer the library did not expect. Keep the last known state meanwhile."""
    ASK_CREDENTIALS = auto()
    """The account's e-mail or password is refused or missing: ask the user again."""
    ASK_CODE = auto()
    """The panel refused the alarm code: ask the user again."""
    NOT_PERMITTED = auto()
    """This account may not do this. Retrying will not help."""
    UNAVAILABLE = auto()
    """The panel cannot be reached: report it as unavailable rather than keep a stale state.
    Calls may succeed again once it is back."""
    CHECK_STATE = auto()
    """A write may have run without its confirmation coming back. Read the state before
    sending it again."""
    FIX_CALL = auto()
    """The call itself is wrong, so nothing was sent. Fix the code that made it."""


class DaitemError(Exception):
    """Generic pydaitem error."""

    code: ClassVar[str] = "error"
    """Short stable identifier of the class, for a translated message."""

    remedy: Remedy = Remedy.RETRY_LATER
    """What to do about this error. Set by the class, refined by some raises."""

    def __init__(self, *args: object, remedy: Remedy | None = None) -> None:
        super().__init__(*args)
        if remedy is not None:
            self.remedy = remedy

    @property
    def placeholders(self) -> dict[str, str]:
        """Values a user-facing message for `code` may show. Empty unless a class says."""
        return {}


class MissingCredentials(DaitemError):
    """A required credential could not be resolved.

    Raised by `resolve_credentials`, before any request is made. A usage error, not a
    condition the API itself returns, but still part of the `DaitemError` hierarchy so
    consumers have exactly one base class to catch.
    """

    code = "missing_credentials"
    remedy = Remedy.ASK_CREDENTIALS


class DaitemUsageError(DaitemError, ValueError):
    """The call itself is wrong, so the API was not asked: retrying it cannot help.

    An arming mode the installation does not offer, a command an automation does not
    accept, a position given with the wrong command, a session opened inside another, an
    account with no installation, a call on a closed client, an id that cannot be a URL path
    segment. Also a `ValueError`, which is what it is.
    """

    code = "usage"
    remedy = Remedy.FIX_CALL


class DaitemAuthError(DaitemError):
    """Authentication failed: bad credentials, or the Keycloak flow changed.

    `ASK_CREDENTIALS` when the account was refused, `RETRY_LATER` when the sign-in flow
    itself did not go as expected: asking for the password again would not help then.
    """

    code = "auth"
    remedy = Remedy.ASK_CREDENTIALS


class DaitemConnectionError(DaitemError):
    """Network or transport failure (DNS, TLS, dropped socket, timeout).

    `RETRY_LATER`, or `CHECK_STATE` when a write was sent and its answer lost: writes are
    never replayed, and the panel may have obeyed.
    """

    code = "connection"


class DaitemApiError(DaitemError):
    """The API answered with an error.

    Carries what it said, so a consumer can log or match it: the HTTP `status`, the
    business `server_message` (one of `ServerMessage` when the app knows it), the free text
    `details`, and the start of the raw answer in `body`. `body` stays out of the message:
    it is the server's text, which could echo what was sent. The subclasses below type the
    messages a consumer should react to. Any other message raises this class itself.
    """

    code = "api"

    def __init__(
        self,
        *args: object,
        status: int | None = None,
        server_message: str | None = None,
        details: str | None = None,
        body: str | None = None,
        remedy: Remedy | None = None,
    ) -> None:
        super().__init__(*args, remedy=remedy)
        self.status = status
        self.server_message = server_message
        self.details = details
        self.body = body


class DaitemForbiddenError(DaitemApiError):
    """403 or `transmitter.error.accessforbidden`: the account lacks rights for this.

    Known cases, both owner-only: reading the logbook, and the schedule endpoints (a
    restricted account gets a 403 reading `/schedule`).
    """

    code = "forbidden"
    remedy = Remedy.NOT_PERMITTED


class DaitemSessionRestrictedError(DaitemForbiddenError):
    """`transmitter.connection.sessionrestricted`: this account may not open a session now."""

    code = "session_restricted"


class DaitemSessionBusyError(DaitemApiError):
    """409: another device already holds the panel session.

    The panel accepts a single session at a time, across all accounts, so a secondary
    account does not work around it. The caller should retry later.
    """

    code = "session_busy"

    def __init__(self, holder: str | None = None, **kwargs: object) -> None:
        self.holder = holder
        detail = f" (held by: {holder})" if holder else ""
        super().__init__(f"Panel session already open{detail}", **kwargs)  # type: ignore[arg-type]

    @property
    def placeholders(self) -> dict[str, str]:
        """`holder`: who holds the session as the API names it, `""` when it does not."""
        return {"holder": self.holder or ""}

    def __reduce__(self) -> tuple[Any, ...]:
        # Rebuilt from `holder`, not from the message, so a pickled copy (across processes,
        # in a log handler) reads the same.
        return (type(self), (self.holder,), self.__dict__)


class DaitemNoSessionError(DaitemApiError):
    """No usable session on the panel, either missing or stale.

    Reading the state requires a session opened by any device. The caller should open one
    (`client.panel.session()`, which the façade does itself) and retry. A 403 on keep-alive
    means the same: the session is gone.
    """

    code = "no_session"


class DaitemBadCodeError(DaitemApiError):
    """`transmitter.connection.badpincode`: the panel refused the alarm code.

    Retrying with the same code cannot succeed. The caller should ask the user for it again.
    """

    code = "bad_code"
    remedy = Remedy.ASK_CODE


class DaitemTransmitterOfflineError(DaitemApiError):
    """The transmitter cannot be reached, so neither can the panel.

    `transmitter.error.ttdisconnected`, or `transmitter.connection.error` during connect.
    Nothing the caller sends will get through until the transmitter is back.
    """

    code = "transmitter_offline"
    remedy = Remedy.UNAVAILABLE


class DaitemRateLimitedError(DaitemApiError):
    """`transmitter.connection.overlimit` or `error.pool.full`: back off before retrying."""

    code = "rate_limited"


class DaitemCommandError(DaitemError):
    """The panel rejected the command or did not confirm it (`commandStatus` != CMD_OK).

    `command_status` holds the raw value, one of `CommandStatus` when the app knows it.
    `CommandStatus.TIMEOUT` means the command may still have run: read the state before
    sending it again.

    `remedy` follows `command_status`: `NOT_PERMITTED` for `FORBIDDEN`, `FIX_CALL` for a
    command the panel does not know, `CHECK_STATE` otherwise, `TIMEOUT` included.
    """

    code = "command"
    remedy = Remedy.CHECK_STATE

    def __init__(
        self, *args: object, command_status: str | None = None, remedy: Remedy | None = None
    ) -> None:
        super().__init__(*args, remedy=remedy or _COMMAND_REMEDIES.get(command_status or ""))
        self.command_status = command_status

    @property
    def placeholders(self) -> dict[str, str]:
        """`command_status`: the raw status the panel answered, `""` when there is none."""
        return {"command_status": self.command_status or ""}


#: What each failed command status calls for. Any other status reads as `CHECK_STATE`.
_COMMAND_REMEDIES: dict[str, Remedy] = {
    CommandStatus.FORBIDDEN: Remedy.NOT_PERMITTED,
    CommandStatus.UNKNOWN: Remedy.FIX_CALL,
}
