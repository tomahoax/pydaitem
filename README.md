# pydaitem

Read and control a Daitem alarm from a shell or from Python, without the mobile app.

pydaitem is an **unofficial** async client for the private Daitem Secure API (Atral
"Topaze" platform). It ships a `pydaitem` command for scripts, cron jobs and automation
tools, and a Python library for programs. It is the foundation of the
[ha-daitem](https://github.com/tomahoax/ha-daitem) Home Assistant integration, but depends
on nothing from Home Assistant.

> **Not affiliated with Daitem or the Atral group.** The API is private, undocumented and
> non-contractual. It may change with any app update. Use it at your own risk, on your own
> hardware and with your own account.

## Installation

```bash
pip install pydaitem
```

Python 3.11 or later. The only dependency is `aiohttp`.

## Command line

Give the command your account and the alarm code it uses, through the environment or an
env file:

```bash
export DAITEM_EMAIL=me@example.com
export DAITEM_PASSWORD='...'
export DAITEM_MASTER_CODE=1234      # the alarm code of this account
```

Then read the alarm, and drive it:

```bash
pydaitem systems                         # installations, for --system-id
pydaitem status                          # panel state, groups, transmitter
pydaitem devices --json                  # inventory and faults, as JSON
pydaitem arm --mode presence --yes       # drives a real alarm
pydaitem arm --groups 1,3 --wait --yes   # two groups, then wait for the exit delay
pydaitem disarm --yes
```

Commands that drive the alarm ask for confirmation, and refuse to run unattended without
`--yes`. The exit code tells a script what happened without parsing text. Code 3 means
another device, usually the mobile app, holds the panel session: retry later rather than
alert.

```bash
pydaitem arm --yes || { [ $? -eq 3 ] && echo "panel busy, retry later"; }
```

Every command, option, JSON shape and exit code: [command line reference](https://github.com/tomahoax/pydaitem/blob/main/docs/cli.md). Its
[recipes](https://github.com/tomahoax/pydaitem/blob/main/docs/cli.md#recipes) cover several accounts, scripting a check after arming and
watching faults.

## Python

`connect()` signs in, picks the account's first installation and closes everything on the
way out:

```python
import asyncio

from pydaitem import ArmMode, connect


async def main() -> None:
    async with connect("me@example.com", "password", "1234") as system:
        status = await system.panel.read()
        print(status.panel_state, status.active_groups)

        if ArmMode.PRESENCE in await system.capabilities.arm_modes():
            await system.commands.arm(ArmMode.PRESENCE)  # drives a real alarm


asyncio.run(main())
```

`system` is a `DaitemSystem`, the stable façade. It is grouped like the API, one namespace
per resource, and opens and releases the panel session for you:

| Namespace | What it does |
|---|---|
| `system.panel` | Panel state, transmitter connectivity |
| `system.inventory` | Devices, faults and firmware versions |
| `system.capabilities` | Arming modes the installation supports |
| `system.commands` | Arm, disarm, arm by group |
| `system.schedule` | Recurring arm and disarm programs (owner accounts) |
| `system.automation` | Gates, garage doors, shutters, lights and plugs |
| `system.scenarios` | List and run the installer's scenarios |
| `system.video` | Cameras and recorded clips |
| `system.logbook` | The event log (owner accounts) |

A call that fails raises a subclass of `DaitemError`. Its `remedy` tells the caller what to
do, for instance retry later or ask for the code again, and its `code` names it for a
translated message.

Sessions, token reuse, errors, panel states and the stability promise:
[Python guide](https://github.com/tomahoax/pydaitem/blob/main/docs/python.md), whose [common tasks](https://github.com/tomahoax/pydaitem/blob/main/docs/python.md#common-tasks) include a
polling loop and waiting for the alarm to settle after a command.

## Before you design around it

A few properties of the API shape any integration. The library works within them.

- The panel accepts one session at a time, across all accounts. While the mobile app
  holds it, a command fails with `DaitemSessionBusyError` (exit code 3).
- The inventory gives faults and inhibition, but not the open or closed state of a
  detector.
- The schedule and the event log are owner-only. A restricted account gets
  `DaitemForbiddenError`.
- For automations, cameras and clips, `pydaitem dump` collects the raw answers a bug report
  needs.

The full list, with the reasons: [API constraints](https://github.com/tomahoax/pydaitem/blob/main/docs/api-constraints.md).

## Documentation

| Page | For |
|---|---|
| [Command line reference](https://github.com/tomahoax/pydaitem/blob/main/docs/cli.md) | Scripts, cron jobs, shells and automation tools |
| [Python guide](https://github.com/tomahoax/pydaitem/blob/main/docs/python.md) | Programs using the library |
| [Host integration](https://github.com/tomahoax/pydaitem/blob/main/docs/host-integration.md) | Long-running hosts, such as Home Assistant: setup, polling, errors, bug reports |
| [API constraints](https://github.com/tomahoax/pydaitem/blob/main/docs/api-constraints.md) | Anyone designing an integration |
| [API map](https://github.com/tomahoax/pydaitem/blob/main/docs/api/README.md) | Every call the app makes, and where the library stands on each |
| [Call reference](https://github.com/tomahoax/pydaitem/blob/main/docs/api-daitem.md) | Requests and answers, call by call |
| [Architecture](https://github.com/tomahoax/pydaitem/blob/main/docs/project-architecture.md) | Contributors |
| [Contributing](https://github.com/tomahoax/pydaitem/blob/main/CONTRIBUTING.md) | How to report, test and propose a change |
| [Changelog](https://github.com/tomahoax/pydaitem/blob/main/CHANGELOG.md) | What changed, and how to migrate |

## Contributing

Bug reports, dumps from installations with automations or cameras, and pull requests are
welcome. Set-up, checks and the rules the code follows: [contributing guide](https://github.com/tomahoax/pydaitem/blob/main/CONTRIBUTING.md).

## Licence

MIT.
