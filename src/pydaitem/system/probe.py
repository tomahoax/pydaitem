"""Every read the API offers, as sent: what a tester returns so support can be added.

`collect_raw` gathers the raw answer of each read that matters to an integration, so one
file from an installation with automations, cameras or scenarios shows what the models
should read. Its shape is for people to read and may change in any release.

The answers hold personal data (names, serial numbers, e-mail addresses). They are redacted
by default (see `pydaitem.redaction`): secrets go, identifiers keep their ends only.
`redact=False` keeps them as sent, for a file that never leaves its owner.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..exceptions import DaitemError, DaitemSessionBusyError
from ..models._shared import find_key
from ..redaction import redact as _redact
from ..redaction import redact_identifier
from .extras import Reader, read_with_one_session

if TYPE_CHECKING:
    from . import DaitemSystem


async def collect_raw(
    system: DaitemSystem, *, logbook_entries: int = 5, redact: bool = True
) -> dict[str, Any]:
    """Raw answers of the reads, with at most one panel session, and why any failed.

    `logbook_entries` caps how many event log entries are kept (0 skips the event log,
    which is slow to answer and owner-only). `redact` hides secrets and identifiers.
    """
    client = system.client
    transport = client._transport
    sid = system.system_id
    user: dict[str, Any] = {}

    async def get(path: str) -> Any:
        return await transport.request("GET", path)

    async def widgets() -> Any:
        if not user:
            user.update(await client.account.get_user())
        return await client.widgets.get(sid, user["userId"])

    async def installation() -> Any:
        record = await client.devices.get_configuration(sid)
        transmitter = find_key(record, "transmitterId")
        connected: bool | str | None = None
        if transmitter:
            # Keep the record even when the connectivity check fails.
            try:
                connected = await client.panel.is_connected(str(transmitter))
            except DaitemError as err:
                connected = _describe(err, redact=redact)
        return {"record": record, "transmitter_connected": connected}

    async def event_log() -> Any:
        # Only the job creation may need the panel: the wait runs after the session ends.
        return await client.logbook.create_job(sid)

    readers: dict[str, Reader] = {
        "state": lambda: get(f"/topaze/v5/systems/{sid}/state"),
        "inventory": lambda: get(f"/topaze/v2/systems/{sid}/configuration"),
        "automatisms": lambda: get(f"/topaze/v5/systems/{sid}/automatisms"),
        "cameras": lambda: get(f"/topaze/v1/systems/{sid}/cameras"),
        "videos": lambda: get(f"/topaze/v6/systems/{sid}/videos"),
        "widgets": widgets,
        "scenarios": lambda: get(f"/topaze/v6/systems/{sid}/scenarios"),
        "schedule": lambda: get(f"/topaze/v5/systems/{sid}/schedule"),
        "installation": installation,
    }
    if logbook_entries > 0:
        readers["logbook"] = event_log
    results, errors = await read_with_one_session(system._state, readers)
    if "logbook" in results:
        await client.panel.wait_released()  # the slow wait must not overlap the session
        try:
            entries = await client.logbook.wait_job(results["logbook"])
            results["logbook"] = {"count": len(entries), "latest": entries[:logbook_entries]}
        except DaitemError as err:
            del results["logbook"]
            errors["logbook"] = err
    return {
        "system_id": sid,
        "redacted": redact,
        "payloads": _redact(results) if redact else results,
        "errors": {name: _describe(err, redact=redact) for name, err in errors.items()},
    }


def _describe(err: DaitemError, *, redact: bool) -> str:
    text = str(err)
    if redact and isinstance(err, DaitemSessionBusyError) and err.holder:
        # The only error text that names a person: who holds the panel session.
        text = text.replace(err.holder, redact_identifier(err.holder))
    return f"{type(err).__name__}: {text}"
