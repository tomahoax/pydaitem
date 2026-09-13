# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and semantic
versioning.

## [Unreleased]

### Added

- Python 3.14 is now tested in CI and declared in the package metadata. The supported floor
  stays at 3.11.

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
  Owner-only, confirmed live: a restricted account gets `DaitemForbiddenError`. Creating a
  new program has never been observed on the live API and is not supported; `set` only
  updates an existing `id`.
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
