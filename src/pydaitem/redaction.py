"""Redaction of API payloads, so a dump or a diagnostics file can be shared in a public issue.

Keys are matched on *fragments* rather than on a list of known keys, on purpose: a raw
payload is where an unmapped value hides when the Daitem side changes, and a key nobody
anticipated must be redacted anyway, not leak because a fixed list missed it.

Two levels, because they serve different purposes in a bug report:

- Secrets are replaced outright. They have no diagnostic value.
- Identifiers (serial numbers, names, e-mail addresses) keep their ends only. They stay
  correlatable across a payload, between the panel and its detectors, without giving away
  whose home it is.

Values carrying no identity (states, flags, counts) are kept as they are: they are what a
report needs.
"""

from __future__ import annotations

from typing import Any

from .const import PRESET_ITEM_NAMES

__all__ = ["redact", "redact_identifier"]

#: Replaced by `***`. `code` covers the alarm code and the API's `codeIndex`, `sessionid`
#: covers `ttmSessionId` without catching a `session_busy` flag.
SECRET_KEY_FRAGMENTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "authorization",
    "credential",
    "jwt",
    "code",
    "sessionid",
    # Camera vendor cloud access: playback credentials, not identifiers.
    "playinfo",
    "deeplink",
    "channelid",
)

#: Kept as `abc...xyz`: still correlatable across the payload, no longer identifying.
IDENTIFYING_KEY_FRAGMENTS = (
    "serialnumber",
    "username",
    "firstname",
    "lastname",
    "useruid",
    "email",
    "name",
    "label",
    "uid",
    "carir",
    "transmitterid",
    "phone",
    "address",
    "city",
    "zipcode",
)

#: Values under an identifying key that are the app's own vocabulary, not a name someone
#: chose: kept readable, since a report about arming modes needs them. A preset the
#: installer named otherwise stays redacted.
APP_VOCABULARY = frozenset(PRESET_ITEM_NAMES)

#: Long strings are cut, so a file stays small enough to attach to an issue.
MAX_STRING_LENGTH = 512

#: Below this, keeping the ends of a value would give most of it away: it is dropped instead.
MIN_PARTIAL_LENGTH = 6

SECRET = "***"


def _normalize(key: str) -> str:
    return key.lower().replace("_", "").replace("-", "")


def is_secret_key(key: str) -> bool:
    """Whether a key holds something with no place in a bug report."""
    return any(fragment in _normalize(key) for fragment in SECRET_KEY_FRAGMENTS)


def is_identifying_key(key: str) -> bool:
    """Whether a key holds something identifying, but useful when partially kept."""
    return any(fragment in _normalize(key) for fragment in IDENTIFYING_KEY_FRAGMENTS)


def redact_identifier(value: str) -> str:
    """The ends of an identifier, enough to correlate it, not enough to identify it.

    Applying it twice gives the same result, so a payload redacted by the library can go
    through a host application's own redaction unchanged.
    """
    if not value:
        return ""
    if len(value) <= MIN_PARTIAL_LENGTH:
        return SECRET
    return f"{value[:3]}...{value[-3:]}"


def redact(value: Any) -> Any:
    """A copy of `value`, any JSON-like shape, safe to share.

    Secrets under a secret-looking key become `***`, identifiers under an identifying key
    keep their ends, long strings are cut. Everything else is kept.
    """
    if isinstance(value, dict):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                redacted[key] = redact(item)
            elif is_secret_key(key):
                redacted[key] = SECRET
            elif is_identifying_key(key) and isinstance(item, str):
                redacted[key] = item if item in APP_VOCABULARY else redact_identifier(item)
            else:
                redacted[key] = redact(item)
        return redacted
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, set):
        return {redact(item) for item in value}
    if isinstance(value, str) and len(value) > MAX_STRING_LENGTH:
        return f"{value[:256]}...{value[-64:]}"
    return value
