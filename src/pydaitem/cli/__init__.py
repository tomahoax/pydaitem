"""Command line interface, for use outside Python.

Exists so a cron job, a shell script, a Node-RED flow or an MQTT bridge can drive the alarm
without writing async Python.

Built on argparse on purpose: the single-dependency promise keeps this library
conflict-free to embed anywhere, and a CLI convenience must not cost users that.

    pydaitem status --json
    pydaitem devices
    pydaitem presets
    pydaitem schedule list
    pydaitem arm --mode away --yes

Exit codes let a caller branch without parsing text. `SESSION_BUSY` in particular is not a
failure: it is the normal outcome when someone has the mobile app open, and an automation
should retry rather than alert.

Split by responsibility across this package: `parser` (the argparse tree and its input
validators), `output` (the shared `--json`/text formatting and the confirmation prompt),
`commands` (systems/status/devices/presets/arm/disarm), `schedule` (the schedule
subcommands), and `app` (dispatch and `main()`, which ties the others together).
"""

from __future__ import annotations

from .app import EXIT_AUTH, EXIT_ERROR, EXIT_OK, EXIT_SESSION_BUSY, EXIT_USAGE, main
from .parser import DEFAULT_TOKEN_FILE, build_parser

__all__ = [
    "DEFAULT_TOKEN_FILE",
    "EXIT_AUTH",
    "EXIT_ERROR",
    "EXIT_OK",
    "EXIT_SESSION_BUSY",
    "EXIT_USAGE",
    "build_parser",
    "main",
]
