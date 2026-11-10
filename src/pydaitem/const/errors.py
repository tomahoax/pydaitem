"""Business error messages and command statuses returned by Topaze, used to type exceptions.

The full list and what each code means: docs/api/reference.md. Tests keep these enums equal
to that list.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class ServerMessage(StrEnum):
    """Business error messages returned by Topaze in the `message` field of an error body.

    The app translates exactly these 29. The server may still send others, so a consumer
    must not assume the list is closed.
    """

    # Panel session
    SESSION_ALREADY_OPEN = "transmitter.connection.sessionalreadyopen"
    """409: another device already holds the panel session."""
    NO_TTM_SESSION = "status.nottmsessionid"
    """500: no session open, `connect` is required first."""
    INVALID_SESSION = "transmitter.error.invalidsessionid"
    """500: a session exists but its id is stale. Same remedy: `connect`."""
    UNEXPECTED = "unexpected.error"
    """500: generic. Sometimes a session error in disguise, see NO_SESSION_DETAIL."""
    BAD_PIN_CODE = "transmitter.connection.badpincode"
    """Wrong alarm code."""
    OVER_LIMIT = "transmitter.connection.overlimit"
    """Too many attempts: back off."""
    SESSION_RESTRICTED = "transmitter.connection.sessionrestricted"
    """This account may not open a session now."""
    CONNECTION_ERROR = "transmitter.connection.error"
    """Transmitter unreachable during connect."""
    VIDEO_LOCKED = "transmitter.connection.videolocked"
    ACCESS_FORBIDDEN = "transmitter.error.accessforbidden"
    """The account lacks the right for this action."""
    TT_DISCONNECTED = "transmitter.error.ttdisconnected"
    """Transmitter offline: the panel cannot be reached at all."""
    BAD_MODULE_VERSION = "system.state.bad.module.version"
    # Codes and users
    CODE_DESYNCHRONIZATION = "zone.code.desynchronization"
    CODE_WRONG_SIZE = "zone.code.wrong.size"
    CODE_RESTRICTED_EXISTS = "zone.code.restricted.already.exists"
    CODE_OWNER_EXISTS = "zone.code.owner.already.exists"
    USER_CODE_INSTALLER = "error.user.code.installer"
    SERVICE_CODE_DUPLICATED = "error.central.servicecode.duplicated"
    SERVICE_CODE_FORBIDDEN = "error.central.servicecode.forbidden"
    USER_CREATION_ERROR = "installer.userCreation.error"
    ALREADY_OWNER = "response.error.isalreadyowner"
    ALREADY_RESTRICTED = "response.error.isalreadyrestricted"
    EMAIL_ALREADY_EXISTS = "error.userUpdate.emailAlreadyExists"
    # Other
    SCENARIO_NO_ACTION = "error.scenario.noaction"
    OWNER_NOT_MIGRATED = "error.owner.notmigrated"
    USER_NOT_FOUND = "error.user.notfound"
    MYDIAGRAL_USER_NOT_FOUND = "error.connect.mydiagralusernotfound"
    SSO_ERROR = "sso.response.error"
    POOL_FULL = "error.pool.full"
    """Server busy: retry later."""


#: Some endpoints report a missing session as a generic `unexpected.error` whose `details`
#: carries the real cause. Matching on that text is a heuristic, but it is the only signal
#: the API gives, and treating it as a session error is strictly better than a generic
#: failure since the remedy is the same.
NO_SESSION_DETAIL: Final = "TTM session not found"


class CommandStatus(StrEnum):
    """`commandStatus` values in command answers. Only `OK` means the panel obeyed."""

    OK = "CMD_OK"
    TIMEOUT = "CMD TIMEOUT"
    """The panel did not confirm in time: the command may or may not have run."""
    UNKNOWN = "UNKNOWN CMD"
    """The panel does not know this command."""
    FORBIDDEN = "ERROR CMD FORBIDDEN"
    """The panel refused the command for this account."""
