"""pydaitem data models.

Deliberately lenient: the API is private and may add or drop fields without notice, so
nothing is validated strictly and the raw payload is kept in `raw`.

Grouped by resource, one module per cluster: `status` (`Group`, `SystemStatus`),
`inventory` (`Anomalies`, `Firmware`, `Device`, `Inventory`), `schedule` (`ScheduleProgram`,
`Schedule`), `account` (`System`), `automation` (`Automatism`), `video` (`Camera`, `Clip`),
`logbook` (`LogEntry`) and `scenario` (`Scenario`).
"""

from __future__ import annotations

from ._shared import _warn_unknown as _warn_unknown  # re-exported for tests
from .account import System
from .automation import Automatism
from .inventory import Anomalies, Device, Firmware, Inventory
from .logbook import LogEntry
from .scenario import Scenario
from .schedule import Schedule, ScheduleProgram
from .status import Group, SystemStatus
from .video import Camera, Clip

__all__ = [
    "Anomalies",
    "Automatism",
    "Camera",
    "Clip",
    "Device",
    "Firmware",
    "Group",
    "Inventory",
    "LogEntry",
    "Scenario",
    "Schedule",
    "ScheduleProgram",
    "System",
    "SystemStatus",
]
