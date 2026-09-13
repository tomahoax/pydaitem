"""Constants for the private Daitem Secure API (Atral "Topaze" platform).

Grouped by theme: `wire` (endpoints and protocol timings), `semantics` (the raw API
vocabulary, this library's own semantic vocabulary, and the mapping between them), `errors`
(business error messages used to type exceptions). Package identity and versioning live
here directly, since `pyproject.toml` reads `VERSION` from this file by regex.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version
from platform import python_version
from typing import Final

from .errors import NO_SESSION_DETAIL, ServerMessage
from .semantics import (
    ARMED_PANEL_STATES,
    RAW_TO_FAULT,
    RAW_TO_PANEL_STATE,
    ArmMode,
    Fault,
    PanelState,
    SystemState,
)
from .wire import (
    ACCESS_TOKEN_TTL,
    API_BASE,
    APP_KEEPALIVE_INTERVAL,
    AUTH_BASE,
    CLIENT_ID,
    REALM,
    REDIRECT_URI,
)


def _dependency_version(package: str) -> str:
    try:
        return _package_version(package)
    except PackageNotFoundError:  # pragma: no cover - environment dependent
        return "unknown"


#: Single source of truth for the version: pyproject reads it from here, so the packaged
#: metadata and the value sent as X-App-Version can never drift apart.
VERSION: Final = "0.1.1"
PROJECT_URL: Final = "https://github.com/tomahoax/pydaitem"

#: Required on every call, and the value must be `eNova`: without it the Azure gateway
#: returns 400 before reaching the API, and any other value returns 500. It is a
#: product-line routing key, not a client identity, so keeping it is not impersonation.
APP_NAME: Final = "eNova"

#: Required by `connect` (400 without it) but the value is free, so we send our own.
APP_VERSION: Final = VERSION

#: Optional everywhere; sent anyway so operators can tell what this client is.
APP_PLATFORM: Final = "python"

#: Free-form server-side, so we identify honestly instead of posing as the mobile app.
USER_AGENT: Final = (
    f"pydaitem/{VERSION} (+{PROJECT_URL}) "
    f"aiohttp/{_dependency_version('aiohttp')} "
    f"Python/{python_version()}"
)

__all__ = [
    "ACCESS_TOKEN_TTL",
    "API_BASE",
    "APP_KEEPALIVE_INTERVAL",
    "APP_NAME",
    "APP_PLATFORM",
    "APP_VERSION",
    "ARMED_PANEL_STATES",
    "AUTH_BASE",
    "CLIENT_ID",
    "NO_SESSION_DETAIL",
    "PROJECT_URL",
    "RAW_TO_FAULT",
    "RAW_TO_PANEL_STATE",
    "REALM",
    "REDIRECT_URI",
    "USER_AGENT",
    "VERSION",
    "ArmMode",
    "Fault",
    "PanelState",
    "ServerMessage",
    "SystemState",
]
