"""Entry point: argument parsing, dispatch to the right command, and exit codes."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Awaitable, Callable, Sequence

from ..credentials import resolve_credentials
from ..exceptions import (
    DaitemAuthError,
    DaitemError,
    DaitemSessionBusyError,
    DaitemUsageError,
    MissingCredentials,
)
from ..system import DaitemSystem, connect
from ..tokens import FileTokenStore
from .commands import (
    _cmd_control,
    _cmd_devices,
    _cmd_logout,
    _cmd_modes,
    _cmd_presets,
    _cmd_status,
    _cmd_systems,
)
from .exit_codes import (
    EXIT_AUTH,
    EXIT_ERROR,
    EXIT_INTERRUPTED,
    EXIT_OK,
    EXIT_SESSION_BUSY,
    EXIT_USAGE,
)
from .extras import (
    _cmd_automate,
    _cmd_automations,
    _cmd_cameras,
    _cmd_clips,
    _cmd_dump,
    _cmd_logbook,
    _cmd_scenario,
    _cmd_scenarios,
)
from .parser import build_parser
from .schedule import _cmd_schedule

__all__ = [
    "EXIT_AUTH",
    "EXIT_ERROR",
    "EXIT_OK",
    "EXIT_SESSION_BUSY",
    "EXIT_USAGE",
    "main",
]


async def _run(args: argparse.Namespace) -> int:
    creds = resolve_credentials(env_file=args.env_file, system_id=args.system_id)
    store = FileTokenStore(args.token_file, account=creds.email)

    # `systems` is what you run to choose a system, so it precedes the façade, and `logout`
    # needs none.
    if args.command == "systems":
        return await _cmd_systems(args, creds, store)
    if args.command == "logout":
        return await _cmd_logout(args, creds, store)

    async with connect(
        creds.email,
        creds.password,
        creds.code,
        system_id=creds.system_id,
        token_store=store,
    ) as system:
        return await _dispatch(args, system)


#: Every subcommand that works on one installation, by name.
_COMMANDS: dict[str, Callable[[argparse.Namespace, DaitemSystem], Awaitable[int]]] = {
    "status": _cmd_status,
    "devices": _cmd_devices,
    "presets": _cmd_presets,
    "modes": _cmd_modes,
    "schedule": _cmd_schedule,
    "arm": _cmd_control,
    "disarm": _cmd_control,
    "automations": _cmd_automations,
    "automate": _cmd_automate,
    "scenarios": _cmd_scenarios,
    "scenario": _cmd_scenario,
    "cameras": _cmd_cameras,
    "clips": _cmd_clips,
    "logbook": _cmd_logbook,
    "dump": _cmd_dump,
}


async def _dispatch(args: argparse.Namespace, system: DaitemSystem) -> int:
    command = _COMMANDS.get(args.command)
    if command is None:  # pragma: no cover - argparse rejects this first
        return EXIT_USAGE
    return await command(args, system)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        return asyncio.run(_run(args))
    except MissingCredentials as err:
        print(f"{err}. Provide them through the environment or --env-file.", file=sys.stderr)
        return EXIT_USAGE
    except DaitemSessionBusyError as err:
        print(f"{err}. Close the Daitem app on your phone and retry.", file=sys.stderr)
        return EXIT_SESSION_BUSY
    except DaitemAuthError as err:
        print(f"Authentication failed: {err}", file=sys.stderr)
        return EXIT_AUTH
    except DaitemUsageError as err:
        print(f"{err}.", file=sys.stderr)
        return EXIT_USAGE
    except DaitemError as err:
        print(f"Error: {err}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return EXIT_INTERRUPTED
