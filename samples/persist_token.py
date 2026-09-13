"""Reuse a session between runs instead of replaying the login form.

Run it twice. The first run authenticates through the Keycloak form and stores the refresh
token; the second resumes from that token, which the debug log makes visible.

    python samples/persist_token.py --env-file ~/.daitem.env

The token file is a credential: it is written owner-readable only, and should be treated
like a password.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from pydaitem import DaitemClient, FileTokenStore, resolve_credentials


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    parser.add_argument("--token-file", type=Path, default=Path("~/.daitem.token"))
    args = parser.parse_args()

    # The library logs which path it took at debug level.
    logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")

    creds = resolve_credentials(env_file=args.env_file)
    store = FileTokenStore(args.token_file)

    async with DaitemClient(creds.email, creds.password, token_store=store) as client:
        user = await client.account.get_user()
        print(f"\nSigned in as {user.get('firstName')} {user.get('lastName')}")
        print(f"Token stored in {Path(args.token_file).expanduser()}")
        print("Run this again: the login form should not be used a second time.")


if __name__ == "__main__":
    asyncio.run(main())
