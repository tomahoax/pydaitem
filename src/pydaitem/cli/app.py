"""Entry point: argument parsing, dispatch to the right command, and exit codes."""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence

from ..credentials import resolve_credentials
from ..exceptions import DaitemAuthError, DaitemError, DaitemSessionBusyError, MissingCredentials
from ..system import DaitemSystem, connect
from ..tokens import FileTokenStore
from .commands import _cmd_control, _cmd_devices, _cmd_presets, _cmd_status, _cmd_systems
from .exit_codes import EXIT_AUTH, EXIT_ERROR, EXIT_OK, EXIT_SESSION_BUSY, EXIT_USAGE
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
    store = FileTokenStore(args.token_file)

    # `systems` is what you run to choose a system, so it precedes the façade.
    if args.command == "systems":
        return await _cmd_systems(args, creds, store)

    async with connect(
        creds.email,
        creds.password,
        creds.code,
        system_id=creds.system_id,
        token_store=store,
    ) as system:
        return await _dispatch(args, system)


async def _dispatch(args: argparse.Namespace, system: DaitemSystem) -> int:
    if args.command == "status":
        return await _cmd_status(args, system)
    if args.command == "devices":
        return await _cmd_devices(args, system)
    if args.command == "presets":
        return await _cmd_presets(args, system)
    if args.command == "schedule":
        return await _cmd_schedule(args, system)
    if args.command in {"arm", "disarm"}:
        return await _cmd_control(args, system)
    return EXIT_USAGE  # pragma: no cover - argparse rejects this first


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
    except DaitemError as err:
        print(f"Error: {err}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:  # pragma: no cover - interactive only
        return EXIT_ERROR
