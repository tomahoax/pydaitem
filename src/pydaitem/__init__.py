"""pydaitem — async client for the private Daitem Secure API (Atral Topaze platform).

Unofficial library, reverse-engineered from the mobile app. Not affiliated with or
endorsed by Daitem or the Atral group, and the API it consumes may change without notice.
"""

from __future__ import annotations

from .client import DaitemClient
from .const import (
    APP_KEEPALIVE_INTERVAL,
    ARMED_PANEL_STATES,
    USER_AGENT,
    VERSION,
    ArmMode,
    Fault,
    PanelState,
)
from .credentials import Credentials, resolve_credentials
from .exceptions import (
    DaitemAuthError,
    DaitemCommandError,
    DaitemConnectionError,
    DaitemError,
    DaitemForbiddenError,
    DaitemNoSessionError,
    DaitemSessionBusyError,
    MissingCredentials,
)
from .models import (
    Anomalies,
    Device,
    Group,
    Inventory,
    Schedule,
    ScheduleProgram,
    System,
    SystemStatus,
)
from .system import DaitemSystem, connect
from .tokens import FileTokenStore, MemoryTokenStore, TokenStore

__version__ = VERSION

__all__ = [
    "APP_KEEPALIVE_INTERVAL",
    "ARMED_PANEL_STATES",
    "USER_AGENT",
    "VERSION",
    "Anomalies",
    "ArmMode",
    "Credentials",
    "DaitemAuthError",
    "DaitemClient",
    "DaitemCommandError",
    "DaitemConnectionError",
    "DaitemError",
    "DaitemForbiddenError",
    "DaitemNoSessionError",
    "DaitemSessionBusyError",
    "DaitemSystem",
    "Device",
    "Fault",
    "FileTokenStore",
    "Group",
    "Inventory",
    "MemoryTokenStore",
    "MissingCredentials",
    "PanelState",
    "Schedule",
    "ScheduleProgram",
    "System",
    "SystemStatus",
    "TokenStore",
    "__version__",
    "connect",
    "resolve_credentials",
]
