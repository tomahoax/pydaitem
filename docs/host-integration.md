# Integrating pydaitem into a host application

How to build pydaitem into a long-running host: a home automation platform, a bridge, a
monitoring service. It follows the life of an integration, from setup to bug reports, and
links to the [Python guide](python.md) for the detail of each call. The
[Home Assistant integration](https://github.com/tomahoax/ha-daitem) is the reference
consumer: the last section maps each step onto its concepts.

Read [API constraints](api-constraints.md) first. Two of them shape everything below: the
panel accepts one session at a time, across all devices, and there is no push, only polling.

## Lifecycle

- One `DaitemClient` per account, one `DaitemSystem` per installation. Several installations
  of one account share the client. See [Several installations](python.md#several-installations).
- Pass the host's own `aiohttp.ClientSession`. The library never closes a session it did not
  open, and signs in on a cookie jar of its own, so sharing it is safe.
- Give the client a `TokenStore` backed by the host's storage, so a restart resumes the
  sign-in instead of replaying the login form. Two async methods are enough. See
  [Reusing a session between runs](python.md#reusing-a-session-between-runs).
- Call `client.close()` when the host unloads the installation. It waits for any panel
  release still running.

## Setup

1. Sign in and list the installations: `client.account.list_systems()`. A wrong password is
   a `DaitemAuthError` whose `remedy` is `ASK_CREDENTIALS`.
2. Let the user pick one when there are several. `System.id` is stable: use it as the
   host's unique id.
3. Check the alarm code with `system.panel.check_code()`. `DaitemBadCodeError` means a wrong
   code. `DaitemSessionBusyError` means the mobile app holds the panel and the code is
   unchecked: ask the user to close it and try again.

Store the e-mail, the password and the code. The code is the one of this account, not
necessarily the owner's master code.

## Polling

Read the state and the inventory on a cycle with `system.read_snapshot()`. It never raises a
`DaitemError`, and keeps each read's failure apart, so a busy panel does not hide the faults.
Five minutes is a good default, faster while an exit delay runs. The recipe is in
[Poll the alarm](python.md#poll-the-alarm).

Keep the load low, since every request reaches the Daitem servers and every panel session
keeps the mobile app out:

- During an exit delay, read the state alone (`panel.read()`), not the inventory.
- Give an action or a diagnostics download the state the last cycle read:
  `panel.read(max_age=...)` returns it without a request.
- Put `client.stats` in the host's diagnostics, to see what the integration costs. See
  [Keep the load on the API low](python.md#keep-the-load-on-the-api-low).

Discover the arming modes once with `system.capabilities.arm_modes()`, after a first read
proved the panel free, and again while `capabilities.discovered` is False. A discovery
blocked by the mobile app is made by the next read that opens a session anyway.

Set `call_timeout` on the client, so a slow or hung server bounds each call rather than
stalls the host: 60 s covers a deferred connect. It is off by default. See
[Bound how long a call may take](python.md#bound-how-long-a-call-may-take).

## Reacting to errors

Every exception carries a `remedy`. A host maps the seven remedies once, instead of matching
exception classes. The full table is in [Errors](python.md#errors).

| `remedy` | During a poll | During a user action |
|---|---|---|
| `RETRY_LATER` | Keep the last state, try next cycle | Tell the user to try again |
| `ASK_CREDENTIALS` | Stop polling, ask for the password | Same |
| `ASK_CODE` | Stop polling, ask for the code | Same |
| `NOT_PERMITTED` | Hide the feature for this account | Tell the user the account may not do it |
| `UNAVAILABLE` | Mark the installation unavailable | Tell the user the panel is unreachable |
| `CHECK_STATE` | Not raised by reads | Read the state before offering to send again |
| `FIX_CALL` | A bug in the host: log it | Same |

To tell the user what happened, key a translated message on the exception's `code` and fill
it from its `placeholders`. Its text is technical and belongs in the log.

## Commands

Send one command at a time per installation: the panel session is shared. A command returns
the new state at once: publish it rather than waiting for the next cycle. While the exit
delay runs, poll faster, or call `system.panel.wait_settled()`.

## Bug reports

- Declare the `pydaitem` logger wherever the host lets users turn debug logging on.
  Without it, the library's lines never reach the log. See
  [See what the library does](python.md#see-what-the-library-does).
- Include `system.collect_raw()` in the host's diagnostics. It is redacted by default, and
  `redact()` redacts the host's own data the same way. See [Diagnostics](python.md#diagnostics).
- A warning about an unknown value (a new panel state, a new fault key) means the API
  changed. Ask the user to report it with a dump.

## Testing

Run the host's own tests against `pydaitem.testing.FakeDaitem`, a fake Daitem service that a
real client talks to unchanged. Each edge case above has a lever: a panel held by another
device, a wrong code, the transmitter offline, a lost answer. See
[Testing your code](python.md#testing-your-code).

## Example: Home Assistant

| Step | pydaitem | Home Assistant |
|---|---|---|
| Shared HTTP session | `DaitemClient(session=...)` | `async_get_clientsession(hass)` |
| Token store | `TokenStore` | The config entry's data |
| Setup checks | `list_systems()`, `check_code()` | Config flow, `test-before-configure` |
| Polling | `read_snapshot()` | `DataUpdateCoordinator` |
| `ASK_CREDENTIALS`, `ASK_CODE` | `err.remedy` | `ConfigEntryAuthFailed`, reauth flow |
| `UNAVAILABLE`, `RETRY_LATER` | `err.remedy` | `UpdateFailed`, or `ConfigEntryNotReady` at setup |
| User-facing errors | `err.code`, `err.placeholders` | `HomeAssistantError(translation_key=..., translation_placeholders=...)` |
| Serialised commands | One at a time | `PARALLEL_UPDATES = 1` |
| Debug logging | Logger `pydaitem` | `"loggers": ["pydaitem"]` in `manifest.json` |
| Diagnostics | `collect_raw()`, `redact()` | `async_get_config_entry_diagnostics` |
| Tests | `FakeDaitem` | `pytest-homeassistant-custom-component` |

The library's CI runs the integration's tests against its current branch every week
(`.github/workflows/consumer.yml`), so a change that would break it shows up before a
release.
