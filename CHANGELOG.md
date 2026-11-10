# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic
versioning.

## [0.3.0b1] - 2026-11-10

Beta, for testing on installations with automations and cameras. Every call is described in
the [API map](docs/api/README.md).

### Added

- A job (a deferred connect, the event log, a video capture) is polled less and less often
  while it runs, from its first interval up to four times it. Cache headers, if the API
  ever sends them, are logged once per endpoint at debug level, to tell whether a
  conditional request would pay. The host guide gives the cadence that keeps the load low.
- Less load on the API. `panel.read()` and `inventory.read()` take `max_age`, to return a
  recent answer without a request, and the state a command answers with counts as read.
  When the API says it is overloaded, or a gateway fails three times in a row, the client
  sends nothing for a growing pause, from 5 s up to 5 min, and raises
  `DaitemRateLimitedError` meanwhile: the panel release still goes out.
  `DaitemClient.stats` counts the requests by endpoint, the retries, the panel sessions and
  how long they were held.
- Guards on time. `DaitemClient(call_timeout=...)` bounds each façade call as a whole, the
  wait for the panel included, and raises `DaitemConnectionError` past it: `CHECK_STATE` if
  a command had left, `RETRY_LATER` otherwise. Off by default. `max_session_hold` (120 s by
  default) frees the panel when a session stays open too long. A request's connection must
  open within 10 s, within its 20 s overall.
- `FakeDaitem.stall()` and `FakeDaitem.latency`, to test timeouts and slow networks.
- A [host integration guide](docs/host-integration.md): lifecycle, setup, polling, errors,
  commands, bug reports and tests, in the order an integration meets them, with their Home
  Assistant counterparts. A weekly CI job runs the Home Assistant integration's tests
  against the current branch.
- `system.panel.check_code()`, for a setup form: it opens a panel session with the code and
  releases it at once, raising `DaitemBadCodeError` when the panel refuses the code.
- `system.read_snapshot()` reads the state and the inventory, each failing on its own into
  `Snapshot.errors`, so one poll cycle is one call.
- The Python guide gives the worst-case duration of each call and how to bound it.
- `pydaitem.testing`, for code that uses pydaitem: `FakeDaitem` serves the sign-in and the
  façade's core on a local port, with levers for each edge case (panel held by another
  device, wrong code, wrong password, transmitter offline, exit delay, unconfirmed command,
  lost answer, any server message, expired sign-in). `status()` builds a `SystemStatus` in
  a given `PanelState`.
- Debug logging that explains an edge case after the fact: one line per request (method,
  path, status, duration, never a body or a header), and for each panel session when it
  opens and how long it held the panel. The lines of one session share a tag.
- `redact()` and `redact_identifier()`, moved from the Home Assistant integration: secrets
  go, identifiers keep their ends. `collect_raw()` and `pydaitem dump` now redact by default,
  `redact=False` and `--no-redact` keep the data as sent. The dump's JSON summary gains
  `redacted`. The app's own preset names stay readable, a name the installer chose does not.
- Every exception says what to do about it. `remedy`, a new `Remedy` enum, is the action:
  `RETRY_LATER`, `ASK_CREDENTIALS`, `ASK_CODE`, `NOT_PERMITTED`, `UNAVAILABLE`,
  `CHECK_STATE` or `FIX_CALL`. `code` is a stable name per class (`session_busy`,
  `bad_code`...) to key a translated message on, and `placeholders` the values such a
  message may show (`holder`, `command_status`). Three cases refine the class's remedy: a
  write sent whose answer was lost is `CHECK_STATE`, a sign-in whose flow misbehaved is
  `RETRY_LATER` rather than `ASK_CREDENTIALS`, and a command error follows its
  `command_status`. A bare 403 on connect asks for the code (`ASK_CODE`), as the Home
  Assistant integration has always read it. The errors table of the Python guide is tested
  against the code.
- A method for every call of the API: 78 in all, 57 of them new. New client namespaces:
  `automation`, `video`, `scenarios`, `devices`, `notifications`, `users` and `widgets`,
  plus alerts, scenarios and PPMS in `commands`, connectivity and mode switch in `panel`,
  Topaze logout, upsell and feedback in `account`, and adding a program in `schedule`
  (neither the façade nor the CLI uses it).
  They mirror the API and are not part of the stable contract. Writes are never replayed
  after a dropped connection.
- Models for what an integration needs: `Automatism`, `Camera`, `Clip`, `LogEntry` and
  `Scenario`, with their vocabularies (`AutomatismCategory`, `AutomatismCommand`,
  `ClipKind`, `ClipCategory`...). Parsing is lenient and keeps `raw`.
- In the façade: the `automation`, `video` and `logbook` namespaces, `read_extras()`
  (automations, cameras and clips with at most one panel session),
  `automation.command()` (refuses a command the automation does not list), `client`, and
  `collect_raw()`, the raw answers of every read for diagnostics.
- CLI commands `automations`, `automate`, `scenarios`, `scenario run`, `modes`, `cameras`,
  `clips`, `logbook` and `dump`. `arm` and `disarm` take `--groups`, `arm` takes `--wait`,
  and `status` reports whether the transmitter is online.
- In the façade: `panel.wait_settled()`, `panel.transmitter_online()` and the `scenarios`
  namespace (`read`, `run`).
- Documentation for developers: the README is a short entry point, with the details in a
  [command line reference](docs/cli.md), a [Python guide](docs/python.md) and
  [API constraints](docs/api-constraints.md).
- The API map: `docs/api/` lists the 78 calls the app makes, its 13 raw states, 29 server
  error codes, command statuses and retry rules. Its single source is
  `docs/api/openapi.yaml`, edited by hand. It replaces `docs/openapi.yaml`. Tests hold the library
  to it.
- Raw states `tempo2` and `partial2`, the second named preset, map to `ARMING` then
  `ARMED_PARTIAL_2`. A consumer polling through an exit delay now also waits on `tempo2`.
- `PanelState.MAINTENANCE` for the installation (`apprent`) and test (`essai`) modes.
- `ServerMessage` lists the 29 codes the app knows. New exceptions for those a consumer
  should react to: `DaitemBadCodeError`, `DaitemTransmitterOfflineError`,
  `DaitemRateLimitedError`, `DaitemSessionRestrictedError`. Their base `DaitemApiError`
  carries `status`, `server_message` and `details`.
- `CommandStatus`, and `DaitemCommandError.command_status` with a message per status.
- `RETRY_LIMIT` and `RETRY_DELAY` in `pydaitem.const`.
- Clips download as bytes (`client.video.download_clip`), and captures, deferred connects
  and the event log share one job poller.
- The inventory reads every device family: sirens, transmitters, transceivers, the box,
  and fire and PPMS triggers join detectors and controls in `Inventory.devices`, so their
  faults reach `pydaitem devices`. `DeviceKind` names the families, `Inventory.of_kind()`
  filters them, `Device.triggered` and `Device.firmwares` are new. `Inventory` also gives
  `alerts_enabled` and `scenarios_enabled`.
- `client.panel.connect()` polls a deferred answer for up to 30 s, and releases the panel if
  it never comes.
- `pydaitem logout` revokes the stored sign-in and deletes the token file.
  `client.logout()` now revokes a token kept only in the store, and always clears it.
- `DaitemApiError.body` keeps the start of the server's raw answer, out of the message.

### Changed

- A timeout is no longer retried, unlike in the app, and the delay between retries varies a
  little around the app's 0.5 s.
- The API map (`docs/api/openapi.yaml`) is factored, a tenth shorter for the same 78
  operations: shared path parameters and the unmodelled answer live once under
  `components`, and a parameter every operation of a path takes sits on the path. A test
  keeps it so.
- Errors that were a bare `DaitemError` now raise a subclass. A call on a closed client and
  an id that cannot be a URL path segment raise `DaitemUsageError`. An installation record
  without transmitter id, and a job `Location` header that is missing or points elsewhere,
  raise `DaitemApiError`. Code catching `DaitemError` is unaffected.
- Every façade method says in its docstring which errors it may raise, and whether it opens
  a panel session. `capabilities.arm_modes()` and `read_extras()` state that they never
  raise a `DaitemError`.
- **Breaking.** The façade is grouped like the API, one namespace per resource, with method
  names of its own. Its former plain reads are gone, without aliases:

  | Before | Now |
  |---|---|
  | `system.read_status()` | `system.panel.read()` |
  | `system.read_inventory()` | `system.inventory.read()` |
  | `system.capabilities.list_presets()` | `system.capabilities.presets()` |
  | `system.capabilities.preset_for(mode)` | none: `commands.arm(mode)` resolves it |
  | `from pydaitem import APP_KEEPALIVE_INTERVAL, USER_AGENT` | `from pydaitem.const import ...` |
  | `Group(1, True)` and any model built from positional arguments | `Group(id=1, active=True)` |

  The stability promise ([Python guide](docs/python.md#stability-promise)) now reads as
  SemVer does before 1.0: a breaking change bumps the minor version.
- The error message is decoded before the HTTP status, as in the app. A 403 that carries a
  session code now raises `DaitemNoSessionError`, and a 403 on keep-alive means the
  session is lost. An unknown error raises `DaitemApiError`, still a `DaitemError`.
- A 401 renews the access token and replays the request once, commands included. A second
  401 raises `DaitemAuthError` instead of a generic `DaitemError`.
- A dropped connection is retried twice, 0.5 s apart, instead of once after 1 s. Commands
  are still never replayed after a dropped connection.
- Presets are matched by the app's item names (`partial_arming_name_1` and `_2`) instead of
  their order, so an installation with only the second preset sees it as `PARTIAL_2`.
- An empty raw state reads as `UNKNOWN` without a warning.
- A client method documented to return an object raises `DaitemApiError` when the API
  answers something else, instead of returning a value of the wrong type.
- **Breaking.** Models take keyword arguments only, so a field added later cannot shift the
  others. `raw` stays out of `repr`, so a model logged as it is no longer prints serial
  numbers or e-mail addresses. `Device`, `System`, `Group` and `Firmware` now keep `raw`
  too, and `Device.kind` is typed `DeviceKind`.
- `Inventory.devices` holds every device family, not only detectors and controls. Code
  that iterates it assuming detectors should use `inventory.sensors`, or filter on `kind`.
- A call the library refuses before sending anything raises `DaitemUsageError`, a
  `DaitemError` and a `ValueError`: an arming mode the installation does not offer, a
  command an automation does not accept, a position with the wrong command, a session
  inside another, an account without installation. Code catching `DaitemError` is
  unaffected. On the command line these exit with code 2 instead of 1, and so does
  `schedule set` with an unknown program id.
- `ServerMessage`, `CameraType`, `ClipFormat` and `DaitemUsageError` are exported from
  `pydaitem`. `APP_KEEPALIVE_INTERVAL` and `USER_AGENT`, details of the wire protocol, are
  only in `pydaitem.const`.
- The stability promise covers everything in `pydaitem.__all__` except `DaitemClient`, says
  which attributes carry the API's own values, and what a minor release may add. A test
  freezes the exports, the façade methods, the exit codes and every JSON shape.
- An unknown fault key logs its warning as soon as the inventory is read, not only when
  `Anomalies.unknown_keys` is.
- Packaging: development status Beta, licence declared as a PEP 639 expression.

- **Breaking for old hosts.** The `aiohttp` floor is 3.10.7 instead of 3.9. On 3.9.0 an
  elapsed timeout surfaced as `CancelledError`, outside `DaitemError`, and 3.10.7 is the
  oldest release the whole test suite passes on. Home Assistant ships a far newer one. A CI
  job now runs the tests against exactly the floor declared in `pyproject.toml`.

### Fixed

- A request that times out raises `DaitemConnectionError`, as documented, instead of a bare
  `TimeoutError` that escaped the `DaitemError` hierarchy and crashed the CLI with a
  traceback. A read that times out is retried like a dropped connection, a write is not.
- Schedule writes (`update_program`, `delete_program`, `set_active`) are no longer replayed
  after a dropped connection, like every other write.
- `logout()` releases Keycloak's answer, and tolerates a timeout.
- `client.panel.connect()` is no longer replayed after a dropped connection or a timeout.
  The replay met the session the panel had just opened, and reported it as busy.
- A success whose body is not JSON (a gateway page) raises `DaitemApiError` instead of a
  bare `ValueError`.
- `pydaitem dump` reports a file it cannot write with exit code 1, not a traceback.
- An error whose message is not a string, or a `connect` answer that is not an object,
  raises `DaitemApiError` instead of a bare `TypeError` or `AttributeError`.
- A deferred `connect` whose poll answer is lost releases the panel, as one that never ends
  already did.
- In `read_extras()` and `collect_raw()`, an answer shaped otherwise than expected fails its
  own read only.
- Clip paths escape what the server sends, and refuse an empty, `.` or `..` segment, so a
  clip id cannot move a request, a `DELETE` among them, to another endpoint.
- `pydaitem dump` writes its file readable by its owner only, since it holds personal data.
- Global options (`--json`, `--yes`, `--token-file`...) work after the command too, as the
  README always wrote them (`pydaitem status --json`). They were rejected with exit code 2.
- `pydaitem automate` reports an unknown automation on stderr, so `--json` output stays
  parseable.
- `arm --groups ""` and `disarm --groups ,` exit with code 2. An empty list used to fall
  through to arming or disarming every group.
- A camera, clip, automation or scenario answer the models cannot parse raises
  `DaitemApiError` from the façade's own reads too, not only from `read_extras`.
- `system.panel.transmitter_online()` finds the transmitter id at any depth of the
  installation record, as `collect_raw` does.
- `collect_raw` keeps the installation record when the connectivity check fails.
- `automation.command()` refuses a position given with any command but `POSITION`, as the
  app never sends one. `pydaitem automate` exits with code 2 on it, before any call.
- `system.logbook.read()` holds a panel session, when the API asks for one, for the job
  creation only. It used to create a second job and hold the panel for up to 60 s while
  waiting for it, which locked out the mobile app.
- The panel session no longer leaks when `connect` does not end normally. A lost answer, a
  cancelled caller (a timeout around a read, Ctrl+C), an answer the models cannot read or a
  deferred connect ending in any error now release the session. Before, it stayed open
  until it expired, and every command met a 409 blamed on the mobile app. A 409 still
  releases nothing, since another device holds the panel.
- The release itself survives a second cancellation and an unexpected error, and always
  forgets the session id. `DaitemClient.close()` waits for a release still running.
- Blocks of `client.panel.session()` on one client wait for each other instead of refusing
  each other with 409. A session opened inside another in the same task raises
  `DaitemError` rather than waiting forever.
- A job poll, its retries included, stops at the job's deadline, and an answer that is not
  a job raises `DaitemApiError` instead of being taken for the result.
- A closed client raises `DaitemError` instead of opening an HTTP session nobody closes.
- `collect_raw` holds the panel for the logbook job creation only, as the façade does.
- `pydaitem arm --wait` exits with code 0 when the wait fails after the panel accepted the
  command, and warns on stderr, so a script does not send it twice.
- The sign-in runs on a cookie jar of its own. A Keycloak single sign-on cookie left in a
  shared `aiohttp` session could sign a client in as another account without checking the
  password.
- The password is posted only to Keycloak's own login action, on the sign-in server's host
  and scheme. Any other form target, from a gateway or error page for instance, is refused
  with `DaitemAuthError`.
- The authorization code is taken only from the app's own redirect, and a Keycloak `error`
  in it becomes `DaitemAuthError`.
- The token exchange, the logout and every write to the API no longer follow redirects,
  which would have sent the code, the refresh token or the alarm code on as they were.
- An unreadable token answer raises `DaitemAuthError`, so a broken refresh falls back to a
  full sign-in instead of escaping as `ValueError` or `KeyError`.
- A token rejected again right after its renewal is forgotten, so the next call signs in
  from scratch. A `TokenStore` whose `save` fails only logs a warning.
- `api_base` and `auth_base` must be https (`ValueError` otherwise), except on a local host.
- `FileTokenStore(path, account=...)` records whose token it holds and ignores a file saved
  for another account, so a token file cannot make the command line drive another
  account's alarm. The command line passes the account, so an existing token file is
  ignored once and replaced after one sign-in. A file owned by another user is ignored, one
  readable by others logs a warning, and a file that is not a JSON object or cannot be
  deleted no longer breaks authentication or `logout()`.
- Every model built from an answer raises `DaitemApiError` when the answer is shaped
  otherwise than expected, instead of a bare `KeyError`, `TypeError`, `ValueError` or
  `AttributeError`. This covers the system list, the state, the inventory, command answers,
  the schedule, the event log, automations, scenarios, cameras and clips. A Home Assistant
  coordinator catching `DaitemError` now marks the panel unavailable instead of crashing.
- The state, the inventory and command answers must be JSON objects. A state value that is
  not a string reads as `UNKNOWN`. The inventory, its firmwares and anomalies, and the
  schedule's programs tolerate odd nested values instead of failing the whole read.
- System and group ids are read as numbers. One that is not a number is refused.
- Every id that goes into a URL path (automation, scenario, program, user, contact, preset,
  serial number...) is escaped, and an empty, `.` or `..` one is refused. An id from the
  server or a caller can no longer move a request, a command or a deletion among them, to
  another endpoint.
- A job path from a `Location` header refuses `.` and `..` segments, escapes, queries and
  fragments, and must belong to the installation that started the job.
- Arming presets read without a `userId` in the user profile fail as `DaitemApiError`, so
  `capabilities.arm_modes()` still offers `AWAY`.
- A non-numeric `DAITEM_SYSTEM_ID` and an unreadable env file raise `MissingCredentials`.
- A pickled `DaitemSessionBusyError` reads the same once unpickled, instead of nesting its
  message in itself.
- Text output and confirmation prompts replace control characters, so a name sent by the
  server cannot rewrite what the terminal shows. Ctrl+C exits with code 130 and a message.
- The env file accepts `export KEY=...`, removes one pair of matching quotes only (a
  password may end with a quote), and warns when other users can read it.
- An API error no longer puts the server's raw answer in its message, which could echo
  what was sent. A refused token names the OAuth error code only.
- A 5xx from the sign-in server raises `DaitemConnectionError` instead of being taken for
  a rejected token, which replayed the login form against a server in trouble. A
  transient failure while resuming the stored token tries that token again next time
  instead of logging in.
- The cron recipe keeps the alarm state in a private folder rather than `/tmp`, and git
  ignores `daitem-dump*.json`.
- `SystemState` is no longer in `pydaitem.client.__all__`.

### Removed

- `samples/`. The command line and the [Python guide](docs/python.md) cover what they
  showed.
- `client.panel.wait_for_stable_state()`, a copy of `system.panel.wait_settled()`, which
  also works inside a session the caller holds.
- `scripts/probe_headers.py`, a one-off experiment. Its findings are in
  [API constraints](docs/api-constraints.md#client-identification).

## [0.2.0] - 2026-09-14

### Added

- Firmware versions, which the inventory endpoint has always returned and this library
  dropped on the floor. `Inventory.central_firmwares` and `.plug_firmwares` carry the full
  entries, and `.software_version`, `.radio_version` and `.transmitter_version` resolve the
  common case: the panel reports `SOFT` and `RADIO`, its transmission module a `SOFT` of its
  own, matching the three versions the mobile app shows. `firmwareType` is kept as a raw string so an unrecognised value survives parsing,
  and an installation that reports nothing yields `None` rather than an empty string.
- Python 3.14 is now tested in CI and declared in the package metadata. The supported floor
  stays at 3.11.

### Notes

- No firmware version exists per detector. The API exposes it for the panel and its
  transmission module only.

## [0.1.1] - 2026-09-13

### Fixed

- The `aiohttp` floor (`>=3.13.4`) made this library impossible to install alongside Home
  Assistant, which pins its own `aiohttp` version exactly (`==3.13.3` as of homeassistant
  2026.2.3): no version could satisfy both at once. Lowered back to `>=3.9`. The CVEs that
  motivated the higher floor are all `aiohttp.web` (server-side) issues; this client never
  runs a production server.

## [0.1.0] - 2026-09-13

First public release.

### Added

- `DaitemClient`, the async low-level client for the private Daitem Secure API, grouped by
  resource: `account`, `panel`, `commands`, `logbook`, `schedule`. Authentication uses
  OAuth2 authorization_code + PKCE, driven headlessly. The client identifies itself
  honestly rather than impersonating the mobile app: only `X-App-Name: eNova` is kept
  as-is, a product routing key the gateway requires.
- `DaitemSystem`, the semantic façade binding a client, a system id and an alarm code, and
  `connect()`, an async context manager yielding a ready one in one step. Grouped into
  `capabilities`, `commands`, `schedule`, it owns the session protocol, preset indices and
  group identifiers, so a change on the Daitem side never reaches consumer code.
- `PanelState`, `ArmMode` and `Fault`: semantic vocabularies owned by the library, mapped
  from the raw API in one place. An unmapped value degrades to `UNKNOWN`
  (`Anomalies.unknown_keys` for faults) with a one-off warning, rather than failing or
  silently reading as absent.
- Full, presence/partial-preset and direct per-group arming and disarming
  (`system.commands.*`), mirroring the mobile app. Commands are never retried: a replayed
  request could arm or disarm twice.
- Recurring arm/disarm programs (`Schedule`, `ScheduleProgram`, `system.schedule.*`).
  Owner-only: a restricted account gets `DaitemForbiddenError`. Creating a new program is
  not supported; `set` only updates an existing `id`.
- The exception hierarchy rooted at `DaitemError` covers every failure the library raises,
  credential resolution included (`MissingCredentials`).
- Refresh token persistence through a pluggable `TokenStore` protocol, with
  `FileTokenStore` (atomic write, mode `0600`) and `MemoryTokenStore`. A client with a
  store resumes its session instead of replaying the Keycloak login form on every start.
- `resolve_credentials()`, resolving from arguments, environment variables then an env
  file, and a `pydaitem` command line (`status`, `devices`, `presets`, `arm`, `disarm`,
  `schedule ...`) with `--json` output and documented exit codes, so cron jobs, shell
  scripts and MQTT bridges need no Python. Built on argparse, adding no dependency.
- `py.typed` (PEP 561), and a documented public API contract in the README separating the
  stable surface from what tracks the API.
- `samples/`: runnable examples for reading state, persisting the token, and controlling
  the alarm.
