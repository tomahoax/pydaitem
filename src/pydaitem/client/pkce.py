"""PKCE helpers for the authorization_code flow (RFC 7636)."""

from __future__ import annotations

import base64
import hashlib
import re
import secrets

_FORM_ACTION_RE = re.compile(r'<form[^>]*\saction="([^"]+)"', re.IGNORECASE)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 (S256)."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _query_param(url: str, key: str) -> str | None:
    match = re.search(rf"[?&]{re.escape(key)}=([^&]+)", url)
    return match.group(1) if match else None
