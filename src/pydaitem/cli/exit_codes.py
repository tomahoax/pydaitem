"""Process exit codes. Part of the CLI's stable contract, see docs/cli.md."""

from __future__ import annotations

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_SESSION_BUSY = 3
EXIT_AUTH = 4
EXIT_INTERRUPTED = 130
