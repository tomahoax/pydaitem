# Python guide

How to use pydaitem from a program. Every call is async and runs on `asyncio`. The library
has two layers:

- **`DaitemSystem`**, the façade bound to one installation. It is the stable surface, and
  it hides the endpoints, the panel session protocol, preset indices and group ids.
- **`DaitemClient`**, the low-level client. It has one method per call of the API, follows
  the API's changes, and is not covered by the stability promise.

Start with the façade, and reach the client only for what the façade does not cover. To
build the library into a long-running host, such as a home automation platform, the
[host integration guide](host-integration.md) follows the steps in order.

## Connecting

`connect()` is the shortest path. It owns the client, picks the account's first
installation unless told otherwise, and closes everything when the block ends:

```python
from pydaitem import connect

async with connect(email, password, code) as system:
    ...
```

| Argument | Meaning |
|---|---|
| `email`, `password` | The Daitem account |
| `code` | The alarm code of this account, not necessarily the owner's master code |
| `system_id` | The installation, when the account has several |
| `token_store` | Where to keep the refresh token between runs, see [below](#reusing-a-session-between-runs) |
| `session` | An `aiohttp.ClientSession` to reuse instead of opening one |

To choose the installation yourself, build the two objects:

```python
from pydaitem import DaitemClient, DaitemSystem

async with DaitemClient(email, password) as client:
    systems = await client.account.list_systems()  # id, name, is_owner
    system = DaitemSystem(client, systems[0].id, code)
```

`DaitemClient` also takes `timeout` (20 s per request by default) and the `session`,
`token_store` arguments above.

## The façade

`DaitemSystem` is grouped like the API, one namespace per resource. Each call opens a panel
session only when it needs one, and releases it as soon as it is done, since the panel
accepts a single session at a time.

### Panel state

```python
status = await system.panel.read()
status.panel_state  # PanelState.ARMED_PRESENCE, for instance
status.is_armed  # fully or partially
status.is_arming  # an exit delay is running, the state will change on its own
status.active_groups  # [1, 3]
```

`panel.read()` first tries to read without a session, so it piggybacks on one the mobile
app already holds instead of disturbing it.

`panel.read(max_age=30)` returns the last state read if it is at most 30 s old, without a
request. The state a command answers with counts as read. The default, 0, always asks.
`inventory.read(max_age=...)` works the same way.

`panel.transmitter_online()` tells whether the transmitter, and so the panel, can be
reached, without a panel session. It answers `None` when the API does not say.

`panel.check_code()` opens a session with the code and releases it at once, for a setup
form that checks the code before saving it. It raises `DaitemBadCodeError` when the panel
refuses the code, and `DaitemSessionBusyError` when another device holds the panel, which
leaves the code unchecked: ask the user to close the mobile app and try again.

### Panel states

| `PanelState` | Meaning | Raw values |
|---|---|---|
| `DISARMED` | Disarmed | `off` |
| `ARMING` | An exit delay is running | `tempo`, `tempogroup`, `tempo1`, `tempo2` |
| `ARMED_FULL` | Every group armed | `on` |
| `ARMED_PRESENCE` | Partially armed through the "presence" preset | `presence` |
| `ARMED_PARTIAL` | Partially armed through the first named preset | `partial1` |
| `ARMED_PARTIAL_2` | Partially armed through the second named preset | `partial2` |
| `ARMED_GROUPS` | Partially armed by direct group activation | `group` |
| `MAINTENANCE` | Installation or test mode | `apprent`, `essai` |
| `TRIGGERED` | Alarm going off | none known yet |
| `UNKNOWN` | No state, or one this library does not know | `""`, anything new |

Use `panel_state`, never the raw `status.state`. The raw values are the 13 the app declares,
detailed in the [API map](api/entities.md#panel-states).

### Inventory and faults

```python
from pydaitem import DeviceKind

inventory = await system.inventory.read()
inventory.sensors  # detectors
inventory.controls  # control devices, such as keypads
inventory.of_kind(DeviceKind.SIREN)  # any other family
inventory.central_anomalies.faults  # {Fault.MAIN_POWER}
for device in inventory.devices:
    print(device.kind, device.name, device.group, device.inhibited, device.anomalies.faults)
inventory.software_version, inventory.radio_version, inventory.transmitter_version
```

`devices` holds every family the app's device screen shows, as `DeviceKind` values:
`SENSOR`, `COMMAND`, `SIREN`, `TRANSMITTER`, `TRANSCEIVER` and `BOX`, plus the
`FIRE_TRIGGER` and `PPMS_TRIGGER` widgets. A trigger sets `device.triggered`, the other
families leave it `None`.

`inventory.alerts_enabled` and `inventory.scenarios_enabled` say whether alerts and
scenarios can be set up on the installation.

Faults live only in the inventory, so read it on every poll cycle to keep fault reporting
current. It needs no panel session.

### Faults

`Anomalies.faults` returns `Fault` values: `MAIN_POWER`, `BACKUP_POWER`, `BATTERY`,
`TRANSMISSION_MEDIA`, `TAMPER_MECHANICAL`, `TAMPER_WIRED`, `RADIO`, `MASKING`, `SENSOR` and
`LOOP`. `anomalies.has(Fault.BATTERY)` answers `None` when the device does not report that
fault at all. A key this library does not know lands in `Anomalies.unknown_keys` and logs a
warning once.

### Arming and disarming

These calls drive a real alarm.

```python
from pydaitem import ArmMode

modes = await system.capabilities.arm_modes()  # frozenset of ArmMode
await system.commands.arm(ArmMode.PRESENCE)
await system.commands.arm_away()  # same as arm(ArmMode.AWAY)
await system.commands.disarm()
await system.commands.arm_groups({1: True, 2: False})
```

`ArmMode.AWAY` arms every group and always works. `PRESENCE`, `PARTIAL` and `PARTIAL_2`
depend on the presets the installer defined. `capabilities.arm_modes()` reads them once
and caches them. `capabilities.discovered` tells whether that read succeeded or the set fell
back to `AWAY` alone, and `capabilities.presets()` returns the presets as the installer
named them. Arming a mode the installation lacks raises `DaitemUsageError` before the
command is sent.

`arm_groups()` drives groups directly, like the app's per-group toggle, without depending
on how presets are configured.

Each command returns the new `SystemStatus`, usually `ARMING` while the exit delay runs.
`system.panel.wait_settled()` reads the state until the delay ends (120 s at most by
default). A command the panel did not confirm raises `DaitemCommandError`. With
`CommandStatus.TIMEOUT` it may still have run: read the state before sending it again.

### Schedule

Owner accounts only.

```python
schedule = await system.schedule.read()
for program in schedule.programs:
    print(program.id, program.day, program.hour, program.minute, program.command)

program = schedule.programs[0]
program.hour = 23
await system.schedule.update_program(program)
await system.schedule.delete_program(program.id)
await system.schedule.set_active(False)  # master switch
```

`command` is `True` for a program that arms and `False` for one that disarms. Creating a
program is left to `client.schedule.add_program`.

### Automations, cameras and clips

```python
for automatism in await system.automation.read():
    print(automatism.label, automatism.category, automatism.available_commands)

gate = ...  # one of the above
await system.automation.command(gate, "PULSE")  # drives real equipment
await system.automation.command(shutter, "POSITION", position=40)

cameras = await system.video.cameras()
clips = await system.video.clips()
```

`automation.command()` refuses, before sending anything, a command the automation does not
list, and a position given with any command but `POSITION`. Commands are
`AutomatismCommand` values.

`read_extras()` reads automations, cameras and clips together, with at most one panel
session for the three. A read that fails leaves its list `None` and its error in
`extras.errors`, so a missing right on videos does not hide the automations:

```python
extras = await system.read_extras()
extras.automatisms, extras.cameras, extras.clips, extras.errors
extras.latest_clip
```

Live camera video is not available: the app plays it through the camera vendor's SDK.

### Scenarios

```python
for scenario in await system.scenarios.read():
    print(scenario.id, scenario.name, scenario.trigger, scenario.actions)

status = await system.scenarios.run(scenario)  # drives a real alarm
```

A scenario runs the actions the installer gave it, which may disarm the alarm: check
`scenario.actions` first. Creating and editing scenarios stays on the low-level client.

### Event log

Owner accounts only. It takes a few seconds, since the API prepares it asynchronously. The
wait never holds the panel session, so the mobile app stays free meanwhile.

```python
for entry in await system.logbook.read():
    print(entry.when, entry.title)
```

Titles are the app's translation keys (`logEvent.36.label2`), kept as they are.

### Diagnostics

`system.collect_raw()` returns the raw answer of every read the library relies on, and why
any failed. It is what `pydaitem dump` writes. Its shape is for people to read and may
change in any release.

It is redacted by default: secrets go, identifiers keep their first and last three
characters. The app's own preset names (`partial_arming_name_presence`...) stay readable,
since they are what a report about arming modes needs. `collect_raw(redact=False)` keeps the personal data as sent. To redact data of
your own the same way, for a host application's diagnostics, use `redact()` on a JSON-like
value and `redact_identifier()` on a single string. Both can run on data already redacted.

```python
from pydaitem import redact, redact_identifier

report = {"raw": await system.collect_raw(), "status": redact(status.raw)}
title = redact_identifier(installation_name)
```

## Common tasks

### Poll the alarm

An integration reads the state and the inventory on a cycle. Five minutes keeps the panel
busy about 1% of the time. Poll faster while an exit delay runs, and keep the last state
when the panel is busy. `read_snapshot()` reads both, each failing on its own, so a busy
panel does not hide the faults, which need no session:

```python
import asyncio

from pydaitem import Remedy


async def watch(system) -> None:
    status = inventory = None
    while True:
        snapshot = await system.read_snapshot()  # never raises a DaitemError
        status = snapshot.status or status  # keep the last one on failure
        inventory = snapshot.inventory or inventory
        error = snapshot.errors.get("status")
        if error is not None and error.remedy in (Remedy.ASK_CREDENTIALS, Remedy.ASK_CODE):
            return  # ask the user again, polling will not fix it
        if error is not None and error.remedy is Remedy.UNAVAILABLE:
            status = None  # the panel is unreachable: report it so, not a stale state
        ...  # publish status.panel_state and inventory faults
        while status is not None and status.is_arming:
            # The exit delay: the state alone, every few seconds. The faults can wait.
            await asyncio.sleep(5)
            status = await system.panel.read()
            ...  # publish status.panel_state
        await asyncio.sleep(300)
```

### Arm and wait for the exit delay

A command returns as soon as the panel accepts it, usually in `ARMING`. `wait_settled()`
reads the state every 2 s until it settles, and returns the last state read, still
`ARMING` if the delay outlasts the timeout:

```python
await system.commands.arm_away()
status = await system.panel.wait_settled(timeout=120)
print(status.panel_state)
```

Each read may open a short panel session when no other device holds one.

### Keep the load on the API low

Every request reaches the Daitem servers, and every panel session keeps the mobile app
out. The library sends as little as it can:

- Concurrent `panel.read()` or `inventory.read()` calls share one request.
- `max_age` lets a caller take a recent answer rather than ask again.
- Reads that need no session run at once, and connect answers with the state.
- When the API says it is overloaded, the client stops sending for a while (see
  [API constraints](api-constraints.md#retries)).

`client.stats` tells what a client sent: requests by endpoint, retries, panel sessions and
how long they were held in all, and calls the breaker answered itself. A host can put it in
its diagnostics:

```python
stats = system.client.stats
stats.total_requests, stats.sessions_opened, stats.session_seconds
stats.requests.most_common(3)  # [("GET /topaze/v5/systems/{id}/state", 288), ...]
```

### Bound how long a call may take

Three guards, all set on the client:

| Setting | Default | What it bounds |
|---|---|---|
| `timeout` | 20 s | Each request. Its connection must open within 10 s at most, so an address that does not answer fails early |
| `call_timeout` | off | Each façade call as a whole, waiting for the panel included |
| `max_session_hold` | 120 s | How long a panel session may stay open before the library frees the panel itself |

Without `call_timeout`, a call that chains requests adds up their bounds. Computed from the
constants:

| Call | Worst case with the default `timeout` |
|---|---|
| `inventory.read()` | about 1 min: three attempts |
| a command (`commands.arm_away()`...) | about 1 min 10 s: connect, an answer deferred up to 30 s, the command |
| `panel.read()` | about 2 min: a read, then a session whose connect answers with the state |
| `logbook.read()` | the API's preparation, up to 1 min, on top of its requests |
| the first call of a client | up to 1 min more for the sign-in |

A long-running host should set `call_timeout`:

```python
client = DaitemClient(email, password, call_timeout=60)
```

Past it, the call raises `DaitemConnectionError`, never a bare `TimeoutError`. Its remedy is
`CHECK_STATE` when a command had already left, since the panel may have obeyed, and
`RETRY_LATER` otherwise. `read_snapshot()`, `read_extras()` and `capabilities.arm_modes()`
still never raise: a budget run out lands in their errors. `wait_settled()` gives each of its
reads the budget and is bounded as a whole by its own `timeout`. `logbook.read()` gives it to
the job creation, the wait for the log having its own bound.

Cancelling a call yourself is safe too: a panel session opened meanwhile is still released,
in a task of its own that `close()` waits for.

`max_session_hold` protects the mobile app from a session left open, by a block that never
ends or a server that hangs. Past it the library releases the panel and logs a warning. The
block's own calls then fail as on a lost session. `None` turns it off.

### Several installations

One client serves every installation of the account. Each `DaitemSystem` needs the alarm
code valid on its installation:

```python
async with DaitemClient(email, password, token_store=store) as client:
    for info in await client.account.list_systems():
        system = DaitemSystem(client, info.id, codes[info.id])
        print(info.name, (await system.panel.read()).panel_state)
```

For several accounts, use one client and one token store per account.

### See what the library does

pydaitem logs through the standard `logging` module, under the `pydaitem` logger and its
children (`pydaitem.client.transport`, `pydaitem.client.panel`, `pydaitem.models`...).
Setting the level on `pydaitem` covers them all. A host application that lets its users
turn debug logging on should name `pydaitem` among its loggers, or the library stays silent.

```python
import logging

logging.basicConfig()
logging.getLogger("pydaitem").setLevel(logging.DEBUG)
```

At debug level, every request logs one line, and every panel session logs when it opens and
how long it held the panel. The lines of one session end with the same tag, so a cycle reads
as a whole:

```
Panel session 3f2a: opening on system 123456
POST /topaze/v5/systems/123456/connect -> HTTP 200 in 412 ms [session 3f2a]
GET /topaze/v5/systems/123456/state -> HTTP 200 in 96 ms [session 3f2a]
POST /topaze/v5/systems/123456/disconnect -> HTTP 200 in 88 ms [session 3f2a]
Panel session 3f2a: released, held 190 ms
```

The tag is drawn locally, it is not the API's session id. Retries, token renewals and
session release failures show up as well. No line carries a body, a header, the alarm code
or a token. A value the library does not know (a new panel state, a new fault key) is
logged once as a warning, at any level.

## Errors

Every exception derives from `DaitemError`. Errors the API reports are `DaitemApiError`,
which carries the HTTP `status`, the business `server_message`, the `details`, and the start
of the raw answer in `body`. `body` stays out of the message, since it is the server's text.

```
DaitemError
├── MissingCredentials
├── DaitemUsageError (also a ValueError)
├── DaitemAuthError
├── DaitemConnectionError
├── DaitemCommandError
└── DaitemApiError
    ├── DaitemSessionBusyError
    ├── DaitemNoSessionError
    ├── DaitemBadCodeError
    ├── DaitemTransmitterOfflineError
    ├── DaitemRateLimitedError
    └── DaitemForbiddenError
        └── DaitemSessionRestrictedError
```

Each exception says what to do about it, so a consumer needs no chain of `isinstance`:

- `remedy`, a `Remedy`, is the action. Most classes have one. A few refine it case by case,
  as the table says.
- `code` is a short, stable name for the class, to key a translated message on.
- `placeholders` holds the values such a message may show, as strings.

The message itself is technical (method, path, server message): keep it for the logs.

| Exception | `code` | `remedy` | When |
|---|---|---|---|
| `DaitemAuthError` | `auth` | `ASK_CREDENTIALS`, or `RETRY_LATER` when the sign-in flow itself misbehaved | Keycloak refused the credentials, or a renewed token too |
| `DaitemConnectionError` | `connection` | `RETRY_LATER`, or `CHECK_STATE` when a write was sent and its answer lost | Network failure, timeout, or a deferred connect that never ended |
| `DaitemSessionBusyError` | `session_busy` | `RETRY_LATER` | Another device holds the panel session (placeholder `holder` says who) |
| `DaitemNoSessionError` | `no_session` | `RETRY_LATER` | No usable panel session. The façade opens one itself |
| `DaitemBadCodeError` | `bad_code` | `ASK_CODE` | The panel refused the alarm code |
| `DaitemTransmitterOfflineError` | `transmitter_offline` | `UNAVAILABLE` | The transmitter, and so the panel, cannot be reached |
| `DaitemRateLimitedError` | `rate_limited` | `RETRY_LATER` | Too many attempts, or the server is busy: back off |
| `DaitemForbiddenError` | `forbidden` | `NOT_PERMITTED`, or `ASK_CODE` for a bare 403 on connect | The account lacks the right (owner-only resources) |
| `DaitemSessionRestrictedError` | `session_restricted` | `NOT_PERMITTED` | This account may not open a session now (a `DaitemForbiddenError`) |
| `DaitemApiError` | `api` | `RETRY_LATER` | Any other server message, kept in `server_message`, or an answer the library did not expect |
| `DaitemCommandError` | `command` | `CHECK_STATE`, `NOT_PERMITTED` or `FIX_CALL`, by the status the panel answered | The panel did not obey (placeholder `command_status`) |
| `DaitemUsageError` | `usage` | `FIX_CALL` | The call is wrong, so nothing was sent: a mode the installation does not offer, a command an automation does not accept, a position with the wrong command, a session inside another, an account without installation, a call on a closed client |
| `MissingCredentials` | `missing_credentials` | `ASK_CREDENTIALS` | `resolve_credentials` found no value for a credential, or an unusable one |

| `Remedy` | What to do |
|---|---|
| `RETRY_LATER` | Try again later and keep the last known state meanwhile |
| `ASK_CREDENTIALS` | Ask the user for the e-mail or password again |
| `ASK_CODE` | Ask the user for the alarm code again |
| `NOT_PERMITTED` | Tell the user this account may not do it. Retrying will not help |
| `UNAVAILABLE` | Report the panel as unavailable rather than keep a stale state |
| `CHECK_STATE` | A write may have run: read the state before sending it again |
| `FIX_CALL` | Fix the code that made the call |

A later minor release may add a `Remedy` member: treat one you do not know as
`RETRY_LATER`.

Which of these a call may raise is in its docstring. Any call may meet the network, the
sign-in, an offline transmitter or a rate limit. A call that opens a panel session may also
meet `DaitemSessionBusyError`, `DaitemBadCodeError` or `DaitemSessionRestrictedError`.
`capabilities.arm_modes()` and `read_extras()` never raise a `DaitemError`.

A polling loop, for instance, only needs the remedy:

```python
from pydaitem import DaitemError, Remedy

try:
    status = await system.panel.read()
except DaitemError as err:
    if err.remedy in (Remedy.ASK_CREDENTIALS, Remedy.ASK_CODE):
        ...  # stop polling and ask the user again
    elif err.remedy is Remedy.UNAVAILABLE:
        ...  # report the panel as unavailable
    else:
        ...  # keep the last state, try again next cycle
```

And a message for the user from the code, in the user's language:

```python
MESSAGES = {"session_busy": "The alarm is in use on another device ({holder})."}


def user_message(err: DaitemError) -> str:
    return MESSAGES.get(err.code, "The alarm did not answer.").format(**err.placeholders)
```

The 29 server messages the app knows are in `ServerMessage`, explained in
the [protocol reference](api/reference.md#server-error-codes).

## Testing your code

`pydaitem.testing` runs a fake Daitem service on a local port: the sign-in and the calls of
the façade's core, with the behaviour that matters to a consumer. One panel session at a
time, a state that cannot be read without one, the alarm code, the transmitter, the exit
delay. A real `DaitemClient` talks to it unchanged, so a test plays an edge case end to end:

```python
from pydaitem import DaitemSessionBusyError, DaitemSystem
from pydaitem.testing import FakeDaitem


async def test_my_code_keeps_the_last_state_while_the_app_holds_the_panel() -> None:
    async with FakeDaitem() as fake, fake.client() as client:
        system = DaitemSystem(client, fake.system_id, fake.code)
        ...  # first cycle: the panel is free
        fake.held_by = "iPhone"
        ...  # next cycle: a command raises DaitemSessionBusyError, a read still works
```

| Lever | Situation |
|---|---|
| `held_by = "iPhone"` | Another device holds the panel session |
| `code`, a code other than the one the client sends | The panel refuses the alarm code |
| `client(password="wrong")` | Keycloak refuses the account |
| `online = False` | The transmitter is unreachable |
| `exit_delay = 30` | An arming stays in its exit delay that many seconds |
| `command_status = "CMD TIMEOUT"` | The panel does not confirm commands |
| `owner = False` | The account is listed as a restricted one (`System.is_owner`) |
| `state`, `groups`, `presets`, `inventory` | What the installation looks like |
| `fail(method, path_suffix, message=...)` | The next matching call answers that server message |
| `drop(method, path_suffix)` | The next matching call loses its answer |
| `stall(method, path_suffix)` | The next matching call never answers, for timeouts |
| `latency = 0.1` | Every answer waits that long, as a slow network |
| `revoke_tokens()` | The sign-in expired: the client signs in again |

`requests` lists every call served, `session_open` tells whether the client still holds the
panel, and `sessions_opened` how many times it took it. Calls outside the façade's core answer
404.

To mock the façade instead, `status(PanelState.ARMED_PRESENCE, groups=[1])` builds a
`SystemStatus` in a given state without knowing the raw values.

The library's own [`tests/test_testing.py`](../tests/test_testing.py) plays each lever once.
`pydaitem.testing` is not covered by the stability promise before 1.0.

## Reusing a session between runs

Without a token store, every process start replays the Keycloak login. With one, the
client resumes from the stored refresh token, and falls back to a full login only if that
token is rejected.

```python
from pydaitem import FileTokenStore, connect

store = FileTokenStore("~/.daitem.token", account=email)
async with connect(email, password, code, token_store=store) as system:
    ...
```

`FileTokenStore` writes atomically, with mode `0600`: the refresh token is a credential.
It does its disk I/O in a thread. With `account`, the file records whose token it holds, and
a file saved for another account is ignored rather than resumed. A file owned by another
user is ignored too, and one readable by others logs a warning. `MemoryTokenStore` keeps the
token in memory. A store holds one account's session: give each account its own. Any object
with `async load()` and `async save(token)` works as a `TokenStore`, for instance one backed
by a host application's own storage. A store whose `save` fails only logs a warning: the
next run signs in again.

## Credentials for scripts

`resolve_credentials()` reads the same variables as the command line (see
[Credentials](cli.md#credentials)), from its arguments first, then the environment, then an
env file:

```python
from pydaitem import resolve_credentials

creds = resolve_credentials(env_file="~/.daitem.env")
async with connect(creds.email, creds.password, creds.code, system_id=creds.system_id) as system:
    ...
```

It raises `MissingCredentials` naming what is missing. The `Credentials` object never
prints its secrets.

## The low-level client

`system.client`, or a `DaitemClient` of your own, has one method per call of the
[API map](api/README.md), grouped by resource: `account`, `panel`, `commands`, `widgets`,
`schedule`, `logbook`, `automation`, `video`, `scenarios`, `devices`, `notifications`,
`users`. Methods take the system id explicitly and return models or raw `dict`s, as the API
sends them.

Two things the façade handles that the client leaves to you:

- Several calls (the state, commands, widgets) need an open panel session. Hold one with
  `async with client.panel.session(system_id, code):`, and keep it short.
- Writes are never replayed after a dropped connection, but nothing stops you from sending
  one twice.

Many of these calls change who can use the alarm or what it does (users, codes,
scenarios, notifications, device inhibition, firmware). The docstrings of their modules
say which.

## Stability promise

A change in the Daitem API should not force a change in your code, as long as you stay on
the stable surface. From 1.0 on, a breaking change to it gets a major version bump. Before
1.0 it bumps the minor version, and the [changelog](../CHANGELOG.md) says how to migrate.

Stable: everything in `pydaitem.__all__`, except `DaitemClient`. That covers:

- `DaitemSystem`, its namespaces (`panel`, `inventory`, `capabilities`, `commands`,
  `schedule`, `automation`, `scenarios`, `video`, `logbook`), `read_snapshot` and its
  `Snapshot`, `read_extras` and `system_id`.
- The vocabularies this library owns: `PanelState`, `ArmMode`, `Fault` and `DeviceKind`.
- The vocabularies the API sends, kept for you to compare against: `AutomatismCategory`,
  `AutomatismCommand`, `AutomatismStateType`, `CameraType`, `ClipCategory`, `ClipFormat`,
  `ClipKind`, `CommandStatus` and `ServerMessage`. Their member names are stable. New
  members may appear when the app gains a value.
- `connect()`, `resolve_credentials`, `TokenStore`, `FileTokenStore` and
  `MemoryTokenStore`.
- `redact()` and `redact_identifier()`. What they hide may grow, never shrink.
- The exception hierarchy rooted at `DaitemError`, each class's `code`, and `Remedy`. The
  `remedy` of a case may be refined when the API reveals it, never its `code`.
- The models, constructed with keyword arguments only: the names and types of their
  attributes, and their semantic properties (`SystemStatus.panel_state`, `.is_armed`,
  `Anomalies.faults`, `Inventory.of_kind()` and the like).
- The command line: its commands, its JSON shapes and its exit codes.

Not stable, since they follow the API:

- `DaitemClient` and its methods, `DaitemSystem.client`, and `pydaitem.const` beyond what
  `pydaitem` exports.
- The shape of `collect_raw()`.
- The values of attributes that carry what the API sent as it is: `SystemStatus.state`,
  `command_status` and `defaults`, `Anomalies.flags` and `.active`, `Device.type`,
  `Firmware.kind`, `Automatism.state` and `.mode`, `Camera.status`, `Scenario.trigger`
  and `.actions`, `LogEntry.title` and `.details`, `capabilities.presets()` items. Their
  names and types are stable, their values are the API's.
- Any `.raw` payload, and anything whose name starts with an underscore.
- `SystemState`, the raw state vocabulary, kept out of `pydaitem.__all__`.

A minor release may add exports, namespaces, methods, model attributes, enum members,
exception subclasses, CLI commands and JSON fields. From 1.0 on, anything removed is first
deprecated for one minor release, with a `DeprecationWarning`. `tests/test_public_api.py`
and the JSON shape test of `tests/test_cli.py` hold the library to this list.

Unknown values degrade instead of breaking. A state this library does not know reads as
`PanelState.UNKNOWN`, an unknown fault key lands in `Anomalies.unknown_keys`, and both log a
warning once, as soon as the answer is read. A Daitem update then shows up in your logs
rather than as a crash.
