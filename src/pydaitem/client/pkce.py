"""PKCE helpers for the authorization_code flow (RFC 7636)."""

from __future__ import annotations

import base64
import hashlib
import html
import re
import secrets
from urllib.parse import parse_qs, urlsplit

_FORM_ACTION_RE = re.compile(r'<form[^>]*\saction="([^"]+)"', re.IGNORECASE)
_FORM_TAG_RE = re.compile(r"<form\b[^>]*>", re.IGNORECASE)
_ACTION_RE = re.compile(r'\saction="([^"]+)"', re.IGNORECASE)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) per RFC 7636 (S256)."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _query_param(url: str, key: str) -> str | None:
    values = parse_qs(urlsplit(url).query).get(key)
    return values[0] if values else None


def _login_form_action(page: str) -> str | None:
    """The action of Keycloak's login form, `kc-form-login`, else of the first form."""
    tags = _FORM_TAG_RE.findall(page)
    preferred = [tag for tag in tags if 'id="kc-form-login"' in tag] or tags
    for tag in preferred:
        match = _ACTION_RE.search(tag)
        if match:
            return html.unescape(match.group(1))
    return None
