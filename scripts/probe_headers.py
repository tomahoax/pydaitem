"""Probe: which headers does the Daitem API actually require?

The client used to replicate the iOS app headers. Identifying honestly as a Python client
is preferable, provided the API accepts it. This script settles it experimentally.

Four profiles are tried, from most mimetic to most transparent. Each replays a read-only
sequence: Keycloak sign-in, user profile, system list, inventory. No command, no arming.

RESULTS (on the reference installation):

- `X-App-Name` is required everywhere and must be `eNova`: without it the Azure gateway
  returns 400 before the API; with "pydaitem" the app returns 500. It is a product routing
  key, not a client identity.
- `X-App-Version` is required by `connect`, but its value is free.
- `X-App-Platform` is optional everywhere.
- `User-Agent` is entirely free.

LIMITATION worth remembering: this probe only covers **read** endpoints. That is what
first led to the wrong conclusion that `X-App-Version` was optional; only `connect`
requires it. Confirm any conclusion here with scripts/smoke.py.

Usage: python scripts/probe_headers.py --env-file ../daitem-api-research/client/.env
"""

from __future__ import annotations

import argparse
import asyncio
import platform
import sys
from pathlib import Path

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from smoke import load_env, require

import pydaitem.client.transport as client_module
from pydaitem import VERSION, DaitemClient

HONEST_UA = (
    f"pydaitem/{VERSION} (+https://github.com/tomahoax/pydaitem) "
    f"aiohttp/{aiohttp.__version__} Python/{platform.python_version()}"
)

MIMETIC_UA = (
    "Daitem Secure/6.0.2 (com.daitem.protectiondirecte; build:2026081701; iOS 26.6.1) "
    "Alamofire/5.11.2"
)

PROFILES: dict[str, dict[str, str]] = {
    "1-mimetic (former default)": {
        "X-App-Name": "eNova",
        "X-App-Platform": "ios",
        "X-App-Version": "6.0.2",
        "User-Agent": MIMETIC_UA,
    },
    "2-honest UA + X-App": {
        "X-App-Name": "eNova",
        "X-App-Platform": "ios",
        "X-App-Version": "6.0.2",
        "User-Agent": HONEST_UA,
    },
    "3-honest UA only": {"User-Agent": HONEST_UA},
    "4-no custom headers": {},
}


async def try_profile(headers: dict[str, str], email: str, password: str) -> str:
    """Replay a read-only sequence with this header profile and report the outcome."""
    client_module.app_headers = lambda: dict(headers)  # type: ignore[assignment]

    steps: list[str] = []
    try:
        async with DaitemClient(email, password) as client:
            await client.login()
            steps.append("login")
            await client.account.get_user()
            steps.append("user")
            systems = await client.account.list_systems()
            steps.append("systems")
            await client.account.get_inventory(systems[0].id)
            steps.append("inventory")
        return f"OK  ({', '.join(steps)})"
    except Exception as exc:
        done = ", ".join(steps) or "nothing"
        return f"FAILED after [{done}]: {type(exc).__name__}: {str(exc)[:140]}"


async def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the headers required by the API")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).parent.parent / ".env")
    args = parser.parse_args()

    load_env(args.env_file)
    email = require("DAITEM_EMAIL")
    password = require("DAITEM_PASSWORD")

    original = client_module.app_headers
    print(f"Honest User-Agent under test:\n  {HONEST_UA}\n")
    results: dict[str, str] = {}
    try:
        for name, headers in PROFILES.items():
            results[name] = await try_profile(headers, email, password)
            print(f"[{name}] {results[name]}", flush=True)
            # Space out sign-ins so Keycloak brute-force protection does not kick in.
            await asyncio.sleep(3)
    finally:
        client_module.app_headers = original

    print("\n=== SUMMARY ===")
    for name, verdict in results.items():
        print(f"  {name:<28} {'OK' if verdict.startswith('OK') else 'FAILED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
