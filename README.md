# pydaitem

**Unofficial** async Python client for the private Daitem Secure API (Atral "Topaze"
platform). It reads and controls a Daitem alarm from code, without going through the
mobile app.

Usable on its own from a script, a cron job, an MQTT bridge or the shell, and used as the
foundation of the [ha-daitem](https://github.com/tomahoax/ha-daitem) Home Assistant
integration. Nothing in the library depends on Home Assistant.

> **Not affiliated with Daitem or the Atral group.** The API it consumes is private,
> undocumented and non-contractual: it may change without notice with any app update. Use
> at your own risk, on your own hardware and with your own account.

## Installation

```bash
pip install pydaitem
```

Only dependency: `aiohttp`, already present in Home Assistant.

## Command line

Reading a state or driving the alarm from a shell, a cron job or a Node-RED flow needs no
Python:

```bash
pydaitem status --json
pydaitem devices
pydaitem presets
pydaitem arm --mode away --yes
```

`presets` prints the raw partial-arming presets (`id` and `name`), the installation's own
wording before `capabilities.arm_modes()` resolves it into the stable `presence`/`partial`
vocabulary — useful to see what an installer named a preset, or what it was renamed to in
the app.

Credentials come from the environment or `--env-file`, and `--token-file` caches the
refresh token so repeated runs reuse a session.

Exit codes let a caller branch without parsing text, and are part of the compatibility
promise:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Generic failure |
| 2 | Usage error, or confirmation impossible |
| 3 | Panel session held by another device |
| 4 | Authentication failure |

Code 3 is not a failure: it is the normal outcome when someone has the mobile app open, so
an automation should retry rather than alert.

```bash
# Arm at night, tolerating someone using the app.
pydaitem arm --yes || [ $? -eq 3 ] && echo "retry later"
```

**Arming and disarming ask for confirmation.** Without a terminal and without `--yes` the
command refuses rather than proceeding: a scheduled job must state its intent, and silently
arming a house because nobody could answer a prompt is the wrong default.

## Schedules

Recurring arm/disarm programs, the same feature the app calls "planning":

```bash
pydaitem schedule list --json
pydaitem schedule set 1 --hour 23 --minute 30 --yes   # only the given fields change
pydaitem schedule set 1 --disarm --yes
pydaitem schedule delete 3 --yes
pydaitem schedule activate --yes     # master switch for the whole schedule
pydaitem schedule deactivate --yes
```

**Creating a new program is not supported.** It was never observed on the live API (no
official documentation exists to confirm the endpoint), so `schedule set` can only update
an existing program's `id` — read it from `schedule list` first. `set`, `delete`,
`activate` and `deactivate` ask for confirmation like `arm`/`disarm`: they drive the alarm
indirectly, by changing when it will arm or disarm itself.

**Owner-only, confirmed live.** A restricted account (the kind recommended for the
`ha-daitem` integration) gets a `DaitemForbiddenError` on every schedule call — use the
account's owner credentials instead.

## Usage from Python

The quickest path is `connect()`, which owns the client and picks the account's first
installation:

```python
import asyncio
from pydaitem import connect


async def main() -> None:
    async with connect("me@example.com", "password", "1234") as system:
        status = await system.read_status()
        print(status.panel_state, status.active_groups)


asyncio.run(main())
```

For finer control, work through `DaitemSystem`. It hides the endpoints, the session protocol, preset indices
and group identifiers, so a change on the Daitem side is absorbed here rather than in your
code.

```python
import asyncio
from pydaitem import DaitemClient, DaitemSystem


async def main() -> None:
    async with DaitemClient("me@example.com", "password") as client:
        systems = await client.account.list_systems()
        system = DaitemSystem(client, systems[0].id, "1234")

        status = await system.read_status()
        print(status.panel_state, status.active_groups)

        inventory = await system.read_inventory()
        print(len(inventory.sensors), "detectors")
        print(inventory.central_anomalies.faults)


asyncio.run(main())
```

Commands are single calls; the session is opened and released for you:

```python
await system.commands.arm_away()
await system.commands.arm_presence()
await system.commands.disarm()

# Only advertise what the installation supports.
modes = await system.capabilities.arm_modes()
```

## Reusing a session between runs

By default every process start replays the Keycloak login form. Pass a token store and the
client resumes from the stored refresh token instead, falling back to a full login only if
that token is rejected.

```python
from pydaitem import DaitemClient, FileTokenStore

store = FileTokenStore("~/.daitem.token")
async with DaitemClient(email, password, token_store=store) as client:
    ...
```

`FileTokenStore` writes atomically with mode `0600`: the refresh token is a credential and
should be treated like a password. It does real disk I/O, so inside Home Assistant back the
store with the config entry instead; the protocol is async precisely so that blocking I/O
never reaches the event loop.

Credentials themselves can be resolved from arguments, environment variables then an env
file:

```python
from pydaitem import resolve_credentials

creds = resolve_credentials(env_file="~/.daitem.env")
```

See `samples/` for runnable examples.

## Public API contract

The point of this library is that **a change in the Daitem API should never force a change
in your code**. That only holds if you stay on the stable surface.

**Stable.** Breaking changes here get a major version bump.

- `DaitemSystem`: its plain reads (`read_status`, `read_inventory`, `system_id`), and its
  resource namespaces `capabilities`, `commands`, `schedule`.
- `PanelState`, `ArmMode`, `Fault`: semantic vocabularies owned by this library.
- `TokenStore`, `FileTokenStore`, `MemoryTokenStore`, `connect()` and
  `resolve_credentials`.
- The command line: its subcommands, its `--json` shape, and its exit codes.
- The exception hierarchy rooted at `DaitemError`.
- Model attributes and the semantic properties: `SystemStatus.panel_state`, `.is_armed`,
  `.is_arming`, `.active_groups`, `Anomalies.faults`, `.has()`, `Inventory.sensors`,
  `Inventory.controls`, `Inventory.software_version`, and so on.

**Not stable.** These track the API and may change in any release.

- `DaitemClient` low-level methods, which mirror endpoints one for one.
- `SystemStatus.state`: the raw API string. Use `panel_state` instead.
- `Anomalies.flags` and `.active`: raw JSON keys. Use `faults` or `has()`.
- Any `.raw` payload, and anything underscore-prefixed.
- `SystemState`, deliberately absent from `pydaitem.__all__`.

**Unknown values degrade, they do not break.** A state this library does not know maps to
`PanelState.UNKNOWN`, an unmapped fault key lands in `Anomalies.unknown_keys`, and both log
a warning once. A Daitem update therefore shows up in your logs instead of silently
reading as "no state".

## API constraints worth knowing before you design around it

These are not library choices, they are measured properties of the API, and they shape
any integration.

**One session per panel, across all accounts.** Calling `connect` while another device
(typically the mobile app) holds the session returns `DaitemSessionBusyError`. Creating a
secondary account does not work around it. Hence `client.panel.session()`, which releases
as soon as possible, and `client.panel.get_status()`, which reads without opening anything
when it can.

**Reading the state requires an existing session**, opened by any device. Without one,
`client.panel.get_state()` raises `DaitemNoSessionError`. `get_status()` handles that case.

**No live per-detector state.** The inventory gives identity, group, inhibition and
**faults** (battery, tamper, radio, masking), but not the open/closed state of a contact.
An opening only shows up in the panel history, while the system is armed.

**Firmware versions come from the inventory too.** The panel reports a `SOFT` and a `RADIO`
image, its transmission module a `SOFT` one of its own, reachable as
`Inventory.software_version`, `.radio_version` and `.transmitter_version`, or in full
through `.central_firmwares` and `.plug_firmwares`. No firmware version exists per detector.

**Faults live in the inventory**, so `read_inventory()` must be called on every poll cycle
for fault reporting to stay live. It needs no panel session, so this is cheap.

**Browser-flow authentication.** The Keycloak realm refuses the `password` grant, so the
library drives the `authorization_code` + PKCE flow server-side, without a browser.

**The logbook and the schedule are owner-only.** A restricted account gets a 403 on both
(confirmed live for the schedule endpoints).

## System states

| `PanelState` | Meaning |
|--------------|---------|
| `DISARMED` | Disarmed |
| `ARMING` | An exit delay is running |
| `ARMED_FULL` | Every group armed |
| `ARMED_PRESENCE` | Partially armed through a named preset |
| `ARMED_GROUPS` | Partially armed by direct group activation |
| `TRIGGERED` | Alarm going off (raw value never captured yet) |
| `UNKNOWN` | A state this library does not know about |

## Client identification

The client identifies itself honestly rather than posing as the mobile app:

```
X-App-Name: eNova
X-App-Platform: python
X-App-Version: <library version>
User-Agent: pydaitem/<version> (+https://github.com/tomahoax/pydaitem) aiohttp/<v> Python/<v>
```

`X-App-Name` keeps the app value because the server requires it to route to the right
product line; every other header is our own. This was verified by probing: without
`X-App-Name` the gateway returns 400, and any other value returns 500.

## Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest          # unit tests, no network, no alarm
ruff check .
mypy src/pydaitem
```

The bundled tests never call the API and never drive an alarm. `scripts/smoke.py` does
exercise the live API and is excluded from the published package.

## Licence

MIT.
