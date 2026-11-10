# Contributing

pydaitem works against a private API that can change with any app update. Help is welcome,
and the most useful kind is often not code.

## Ways to help

| You have | Most useful contribution |
|---|---|
| An installation with automations, cameras or clips | A dump. See [diagnostics](docs/cli.md#diagnostics). |
| A bug | An issue with the version (`pip show pydaitem`), the command or code, the exit code and the `-v` output |
| An app update that broke something | An issue describing the call that changed and what it now answers |
| A fix or a feature | A pull request, following the rest of this guide |

A dump and a `-v` log hold personal data: names, serial numbers, e-mail addresses,
installation ids. Replace them before you attach anything to an issue.

For anything larger than a small fix, open an issue first so the approach is agreed before
you write it. This matters most for the façade and the command line, which carry the
[stability promise](docs/python.md#stability-promise).

## Set up

Python 3.11 or later.

```bash
git clone https://github.com/tomahoax/pydaitem.git && cd pydaitem
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

Then read the [architecture](docs/project-architecture.md) and the
[API constraints](docs/api-constraints.md). They explain most of the rules below.

## Checks

The same as the CI (`.github/workflows/test.yml`), which runs them on Python 3.11 to 3.14:

```bash
ruff check . && ruff format --check .
mypy src/pydaitem scripts
pytest
```

A pull request is merged only when all of them pass.

## Rules the code follows

### One dependency

The library depends on `aiohttp` alone, with a low version floor, because Home Assistant
pins its own `aiohttp` and any other requirement can make pydaitem uninstallable next to it.
Do not add a runtime dependency. The tests use aiohttp's own test server rather than a
mocking library, for the same reason.

### Two layers

- `client/` mirrors the API: one method per call, with the path written as a literal string
  where the request is made, so the tests can match it against the API map. It may change
  in any release.
- `system/` is the stable façade: one namespace per resource of the API map, with verbs of
  its own and no aliases. Renaming or removing anything there is a breaking change.

A few rules hold across both:

- Every failure that reaches the caller is a `DaitemError` subclass. A bare `TimeoutError`,
  `KeyError` or `ValueError` escaping the library is a bug.
- A command, or any other write, is sent with `retry=False`. After a dropped connection the
  panel may have obeyed, and only the answer was lost.
- The panel accepts one session at a time, across all accounts. Hold one only for the
  length of one command or one read.

### The API map comes first

[`docs/api/openapi.yaml`](docs/api/openapi.yaml) describes every call the app makes, and it
is edited by hand. To add or change a call:

1. Describe it in `openapi.yaml`. Set `x-coverage` to `client` or `facade`, and
   `x-observed: true` only when the call was seen in captured traffic.
2. Add the client method, and a façade method when it is an action most users need.
3. Test it against a local server.

`tests/test_api_spec.py` and `tests/test_api_spec_vs_library.py` fail when the map and the
library disagree.

### What a contribution may contain

Do not contribute code, resources or excerpts taken from the app itself: describe the
behaviour instead.

### Tests

- The tests never call the real API. HTTP tests run against `aiohttp.test_utils.TestServer`,
  as in `tests/test_extras.py`.
- A fix comes with a test that fails without it.
- `scripts/smoke.py` runs against a live installation, for maintainers before a release.
  Without `--dry-run` it arms and then disarms a real alarm.

### Secrets and personal data

Never commit credentials, alarm codes, token files, dumps or captured answers. The
`.gitignore` covers the usual names (`.env`, `*.token`), but check `git status` before you
commit.

## Documentation

- English, British spelling, sentence case headings, short sentences.
- Each fact lives on one page, and the others link to it. The
  [documentation map](README.md#documentation) says which page holds what.
- The command line's commands, options, JSON shapes and exit codes are part of the
  stability promise. Update [the reference](docs/cli.md) in the same pull request as the
  code.

## Changelog and versions

- Add an entry under `Unreleased` in [CHANGELOG.md](CHANGELOG.md), in the section that fits:
  Added, Changed, Fixed or Removed.
- Versions follow semantic versioning. Before 1.0, a breaking change to the façade, the
  command line output or the exit codes bumps the minor version, and the Changed section
  gives the migration.
- The version is set in one place, `VERSION` in `src/pydaitem/const/__init__.py`.

## Commits and pull requests

- Branch from `dev` and open the pull request against it.
- Keep one topic per commit. Write the message in the imperative and say why the change is
  needed.
- In the pull request, say how you checked the change, and whether you tried it on a real
  installation.

## Releases

Maintainers only. Publishing a GitHub release tagged `v` followed by `VERSION` (for
instance `v0.3.0b1`) runs `.github/workflows/publish.yml`. It runs the tests, checks that
the tag matches the version, then builds and publishes to PyPI. Publish pydaitem before the
ha-daitem version that depends on it.

## Licence

By contributing, you agree that your contribution is released under the project's
[MIT licence](LICENSE).
