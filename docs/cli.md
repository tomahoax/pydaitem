# Command line reference

The `pydaitem` command reads and drives a Daitem alarm from a shell, a cron job or any tool
that can run a process (Node-RED, an MQTT bridge, a CI job). It is installed with the
library and needs no Python code. `python -m pydaitem.cli` runs the same thing.

```bash
pydaitem [global options] <command> [command options]
```

## Credentials

The command needs three values and accepts a fourth:

| Variable | Meaning |
|---|---|
| `DAITEM_EMAIL` | The account's e-mail address |
| `DAITEM_PASSWORD` | The account's password |
| `DAITEM_MASTER_CODE` | The alarm code of this account, not necessarily the owner's master code |
| `DAITEM_SYSTEM_ID` | The installation to use. Optional, the first one otherwise |

They are read from the environment first, then from the file given with `--env-file`. That
file holds one `KEY=VALUE` per line, optionally prefixed with `export`. Blank lines and lines
starting with `#` are ignored, and one pair of matching quotes around a value is removed. A
file readable by other users logs a warning.

```bash
# ~/.daitem.env, readable by you only (chmod 600)
DAITEM_EMAIL=me@example.com
DAITEM_PASSWORD="..."
DAITEM_MASTER_CODE=1234
```

A missing value exits with code 2 and names it.

The first run signs in through Keycloak and stores the refresh token in `~/.daitem.token`
(mode `0600`), with the account it belongs to. Later runs of the same account resume from it
instead of replaying the login. The file is a credential: keep it private. `pydaitem logout`
revokes it and deletes the file, which forces a fresh login. A file owned by another user is
ignored.

## Global options

They go before or after the command: `pydaitem --json status` and `pydaitem status --json`
are the same.

| Option | Effect |
|---|---|
| `--env-file FILE` | Read credentials from this file too |
| `--token-file FILE` | Where to store the refresh token (default `~/.daitem.token`) |
| `--system-id ID` | Installation to use, from `pydaitem systems` |
| `--json` | Print JSON instead of text |
| `-y`, `--yes` | Confirm an action without asking |
| `-v`, `--verbose` | Debug logging on stderr |

## Commands

| Command | What it does | Drives something |
|---|---|---|
| `systems` | List the installations this account can reach | |
| `logout` | Revoke the stored sign-in and delete the token file | |
| `status` | Panel state, active groups and whether the transmitter is online | |
| `devices` | Device inventory and active faults | |
| `modes` | Arming modes the installation supports, for `arm --mode` | |
| `presets` | Partial arming presets as the installation names them | |
| `arm [--mode MODE \| --groups IDS] [--wait [S]]` | Arm everything, a mode, or chosen groups | Yes |
| `disarm [--groups IDS]` | Disarm everything, or chosen groups | Yes |
| `schedule list` | The recurring arm and disarm programs | |
| `schedule set ID [...]` | Change an existing program | Yes |
| `schedule delete ID` | Delete a program | Yes |
| `schedule activate`, `schedule deactivate` | Turn the whole schedule on or off | Yes |
| `automations` | Gates, garage doors, shutters, lights and plugs | |
| `automate ID COMMAND [--position N]` | Send a command to an automation | Yes |
| `scenarios` | Scenarios defined on the installation | |
| `scenario run ID` | Run a scenario. It may disarm the alarm | Yes |
| `cameras` | Cameras and their status | |
| `clips` | Recorded clips | |
| `logbook [--limit N]` | The event log, newest first (50 entries by default) | |
| `dump [--output FILE] [--logbook N] [--no-redact]` | Write the raw answer of every read to a file | |

### Arming and disarming

```bash
pydaitem modes                          # away, presence...
pydaitem arm --mode presence --yes
pydaitem arm --groups 1,3 --yes         # groups 1 and 3
pydaitem disarm --groups 3 --yes        # group 3
pydaitem arm --yes --wait               # then wait for the exit delay to end
```

`--mode` takes `away` (the default), `presence`, `partial` or `partial_2`. A mode works
only when the installation defines a preset for it, and exits with code 2 otherwise:
`modes` lists those that do, `presets` shows them as the installer named them.

`--groups` sends the listed groups only, like the app's per-group switches. Check `status`
afterwards for the groups left out. It cannot be combined with `--mode`.

`arm` returns as soon as the panel accepts the command, usually in the `arming` state.
`--wait` then reads the state until the exit delay ends, for 120 s at most or the number of
seconds given, and prints the settled state. Each read may open a short panel session. If
the wait fails after the panel accepted the command, `arm` still exits with code 0, prints
the state the command returned and warns on stderr, so a script does not send it twice.

### Scenarios

```bash
pydaitem scenarios                      # ids, names, triggers
pydaitem scenario run 4                 # asks first
```

A scenario runs the actions the installer gave it, which may include disarming the alarm.

### Schedule

`schedule set` changes only the fields it is given:

```bash
pydaitem schedule list
pydaitem schedule set 1 --hour 23 --minute 30 --yes
pydaitem schedule set 1 --day saturday --disarm --groups 1,2 --yes
```

| Option | Value |
|---|---|
| `--day` | `monday` to `sunday` |
| `--hour`, `--minute` | 0 to 23, 0 to 59 |
| `--arm` or `--disarm` | What the program does at that time |
| `--groups` | Comma-separated group ids |

Creating a program is not supported. Create it in the app, then change it here. The schedule is owner-only, so a
restricted account gets exit code 1 with `DaitemForbiddenError`.

### Automations

```bash
pydaitem automations              # ids, categories, states and accepted commands
pydaitem automate gate-1 PULSE    # asks first
pydaitem automate shutter-2 POSITION --position 40 --yes
```

`automate` refuses, before sending anything and with exit code 2, a command the automation
does not list. `--position` goes with `POSITION` only, and `POSITION` needs it: any other
combination exits with code 2 too.

### Diagnostics

`dump` writes the raw answer of every read the library relies on to a JSON file, readable by
its owner only. A dump from an installation with automations, cameras or clips is what a
report about them needs. It is redacted by default: secrets (tokens, codes, session ids) are
removed, and identifiers (names, serial numbers, e-mail addresses) keep their first and last
three characters, enough to correlate them across the file. The app's own preset names stay
readable. Read it before sharing all the same. `--no-redact` keeps everything as sent, for a
file that stays with you.

## Confirmation

Every command marked "Drives something" asks `[y/N]` first. Without a terminal to ask on
and without `--yes`, it refuses with exit code 2 instead of proceeding. A scheduled job
therefore states its intent explicitly.

## Exit codes

They are part of the stability promise.

| Code | Meaning | What a script should do |
|---|---|---|
| 0 | Success | |
| 1 | Any other failure: network, API error, refused command | Alert |
| 2 | Usage error (an unknown id, a mode or command the installation does not offer), missing credential, or confirmation refused | Fix the call |
| 3 | Another device holds the panel session | Retry later, it is not a failure |
| 4 | Authentication failed | Check the credentials |
| 130 | Interrupted with Ctrl+C | |

Error messages go to stderr, so stdout stays parseable with `--json`.

## JSON output

With `--json`, each command prints one JSON object on stdout. Its shape is part of the
stability promise: fields may be added, not removed or renamed. Two values are the API's
own and follow it: the items of `presets` and the `details` of `logbook` entries.

| Command | Shape |
|---|---|
| `systems` | `{"systems": [{"id", "name", "owner", "vendor"}]}` |
| `logout` | `{"signed_out"}` |
| `status` | `{"system_id", "panel_state", "armed", "arming", "active_groups", "transmitter_online"}` |
| `modes` | `{"modes", "discovered"}` |
| `devices` | `{"panel": {"type", "has_io_board", "faults"}, "devices": [{"name", "kind", "group", "inhibited", "faults", "triggered"}]}` |
| `presets` | `{"presets": [{"id", "name", ...}]}`, as the API sends them |
| `arm`, `disarm` | `{"panel_state", "active_groups"}` |
| `schedule list` | `{"global_activation", "max_program_count", "programs": [{"id", "day", "hour", "minute", "command", "groups"}]}` |
| `schedule set` | One program, as in `schedule list` |
| `schedule delete` | `{"deleted"}` |
| `schedule activate`, `deactivate` | `{"global_activation"}` |
| `automations` | `{"automations": [{"id", "label", "category", "commands", "state", "position"}]}` |
| `automate` | `{"id", "sent"}` |
| `scenarios` | `{"scenarios": [{"id", "name", "active", "trigger"}]}` |
| `scenario run` | `{"id", "panel_state", "active_groups"}` |
| `cameras` | `{"cameras": [{"id", "name", "type", "model", "status"}]}` |
| `clips` | `{"clips": [{"id", "taken_at", "kind", "category", "device_uid", "duration_ms"}]}` |
| `logbook` | `{"entries": [{"date", "title", "details"}]}` |
| `dump` | `{"output", "read", "failed", "redacted"}` |

`panel_state` takes the values of [`PanelState`](python.md#panel-states). A program's
`command` is `"arm"` or `"disarm"`. `transmitter_online` is `null` when the API does not
say. `discovered` is `false` when the presets could not be read, so only `away` is
certain. Fault names are those of [`Fault`](python.md#faults). A device's `kind` is one of
the [`DeviceKind`](python.md#inventory-and-faults) values, such as `sensor`, `siren` or
`box`, and `triggered` is `null` except on fire and PPMS triggers.

## Recipes

The JSON examples use [jq](https://jqlang.org/).

### Several installations or accounts

Read `pydaitem systems`, then name the installation on every call, or set
`DAITEM_SYSTEM_ID`:

```bash
pydaitem systems
pydaitem --system-id 123456 status
```

For several accounts, give each one its own env file and its own token file. The token
file records the account it belongs to: given another account's credentials, it is ignored
and the command signs in again, so separate files only save a sign-in each time you switch.

```bash
pydaitem --env-file ~/.daitem-home.env --token-file ~/.daitem-home.token status
pydaitem --env-file ~/.daitem-office.env --token-file ~/.daitem-office.token status
```

### Read one value

```bash
pydaitem status --json | jq -r .panel_state     # disarmed, arming, armed_full...
pydaitem status --json | jq .armed              # true or false
```

### Watch faults

List what reports a fault, panel included:

```bash
pydaitem devices --json | jq -r '
  (.panel.faults | select(length > 0) | "panel: \(join(", "))"),
  (.devices[] | select(.faults != []) | "\(.name): \(.faults | join(", "))")'
```

Alert only when something does:

```bash
if pydaitem devices --json | jq -e '[.panel.faults, .devices[].faults] | flatten | length > 0' > /dev/null; then
  echo "fault reported"
fi
```

### Arm, and check it worked

```bash
state=$(pydaitem arm --yes --wait --json | jq -r .panel_state)
[ "$state" = armed_full ] || echo "alarm not armed: $state" >&2
```

### Poll from cron

Read the state every five minutes, and keep the last good answer when a read fails, for
instance while the mobile app holds the panel. The state tells when the house is empty, so
keep it in a folder only you can read, created once with `mkdir -m 700 -p ~/.cache/pydaitem`:

```cron
*/5 * * * * cd ~/.cache/pydaitem && pydaitem --env-file ~/.daitem.env status --json > alarm.new 2>> alarm.err && mv alarm.new alarm.json
```

Five minutes keeps the panel busy about 1% of the time, so the mobile app rarely finds it
taken.

### Arm at night, tolerating a busy panel

```bash
for attempt in 1 2; do
  pydaitem --env-file ~/.daitem.env arm --yes && break
  [ $? -eq 3 ] || exit 1
  sleep 60
done
```

### See what happens

`-v` logs the retries, token renewals and session release failures on stderr, without
changing the output on stdout:

```bash
pydaitem -v status 2> debug.log
```
