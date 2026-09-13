"""Endpoints and protocol timings for the private Daitem Secure API."""

from __future__ import annotations

from typing import Final

API_BASE: Final = "https://appv3.tt-monitor.com"
AUTH_BASE: Final = "https://auth.atraltech.com"
REALM: Final = "daitem"
CLIENT_ID: Final = "daitem-secure-app"
REDIRECT_URI: Final = "daitemsecure://auth"

#: Keycloak access token lifetime, measured from the JWT (exp - iat).
ACCESS_TOKEN_TTL: Final = 1800

#: keepAlive interval used by the official app. Polling the state is enough to keep the
#: session alive, so keepAlive is not required.
APP_KEEPALIVE_INTERVAL: Final = 480
