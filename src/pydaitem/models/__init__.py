"""pydaitem data models.

Deliberately lenient: the API is private and may add or drop fields without notice, so
nothing is validated strictly and the raw payload is kept in `raw`.

Grouped by resource, one module per cluster: `status` (`Group`, `SystemStatus`),
`inventory` (`Anomalies`, `Firmware`, `Device`, `Inventory`), `schedule` (`ScheduleProgram`,
`Schedule`), and `account` (`System`).
"""

from __future__ import annotations

from ._shared import _warn_unknown as _warn_unknown  # re-exported for tests
from .account import System
from .inventory import Anomalies, Device, Firmware, Inventory
from .schedule import Schedule, ScheduleProgram
from .status import Group, SystemStatus

__all__ = [
    "Anomalies",
    "Device",
    "Firmware",
    "Group",
    "Inventory",
    "Schedule",
    "ScheduleProgram",
    "System",
    "SystemStatus",
]
