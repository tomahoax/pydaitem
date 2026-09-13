# Application architecture

How `pydaitem` itself is put together: package layout, the composition pattern used
throughout, and the choices that follow from being a standalone library rather than
something tied to a particular caller.

## Package layout

```
src/pydaitem/
  client/    Low-level client, one namespace per API resource, mirrors the API one for one.
  system/    Semantic façade bound to one installation: the stable, recommended surface.
  models/    Data classes returned by both layers, grouped by domain.
  const/     Network configuration, semantic vocabulary, and the raw-to-semantic mappings.
  cli/       Command line entry point.
  tokens.py       Refresh-token persistence protocol and implementations.
  credentials.py  Credential resolution for scripts and command line tools.
  exceptions.py   The exception hierarchy, rooted at `DaitemError`.
```

`client/` and `system/` are deliberately separate layers with different stability
guarantees (see the README's "Public API contract"): `client/` changes whenever the Daitem
API does, `system/` absorbs that change so callers do not have to.

## Composition pattern

Both `client/` and `system/` are built the same way: a small, shared, mutable state object
(`_ClientState`, `_SystemState`) carries configuration and cross-cutting state (tokens, the
underlying HTTP session, the current panel session id), and every service receives exactly
the pieces it depends on through its constructor rather than reaching into a shared base
class.

```
_ClientState ──► _Auth ──► _Transport ──┬──► _Account ──► _Commands
                                        ├──► _Panel
                                        ├──► _Logbook
                                        └──► _Schedule

_SystemState ──► _Capabilities ──► _Commands
             └─► _Schedule
```

The façade assembles these services and exposes them as public attributes, one namespace
per resource, with no delegation boilerplate:

```python
class DaitemClient:
    def __init__(self, email, password, ...) -> None:
        self._state = _ClientState(...)
        self._auth = _Auth(self._state)
        self._transport = _Transport(self._state, self._auth)
        self.account = _Account(self._transport)
        self.panel = _Panel(self._state, self._transport)
        self.commands = _Commands(self._transport, self.account)
        self.logbook = _Logbook(self._transport)
        self.schedule = _Schedule(self._transport)
```

Plumbing that is not itself a resource (`login`, `close`, `read_status`, `read_inventory`,
...) stays as a plain method or property directly on the façade instead of living under a
namespace. A dependency between two services (`_Commands` needing `_Account` to resolve a
preset before arming, for instance) is an explicit constructor argument, so it is visible
and type-checked rather than an implicit assumption about call order.

Each service, and each model cluster, lives in its own module, named after the resource it
covers (`account.py`, `panel.py`, `commands.py`, ...). A module stays private to its
package (classes carry a leading underscore); only the façade and the namespaces it exposes
are public.

## Models

`models/` groups data classes by the domain they describe rather than by which endpoint
produced them: `status` (`SystemStatus`, `Group`), `inventory` (`Inventory`, `Device`,
`Anomalies`), `schedule` (`Schedule`, `ScheduleProgram`), `account` (`System`). Every class
is a `dataclass(slots=True)` with a `from_json` constructor and keeps the original payload
in `raw`, since the API is private and may add or drop fields without notice — nothing is
validated strictly.

## Vocabulary and mappings

`const/` keeps the raw API vocabulary (`SystemState`, not part of the public contract)
separate from the vocabulary this library owns and guarantees (`PanelState`, `ArmMode`,
`Fault`), with the mapping between them centralised in a small number of dictionaries
(`RAW_TO_PANEL_STATE`, `RAW_TO_FAULT`). An API value with no entry degrades to `UNKNOWN`
(or an `unknown_keys` entry) with a one-off warning, rather than failing or silently
reading as absent — so an API change surfaces in a consumer's logs instead of vanishing.

## Dependency policy

A single runtime dependency, `aiohttp`. Keeping it to one avoids any resolution conflict
and keeps the library light enough to embed in any async environment; the client is async
throughout for the same reason a synchronous HTTP call would be a poor fit anywhere the
library runs inside someone else's event loop. The command line interface is built on
`argparse`, part of the standard library, so the convenience of a CLI does not add a
dependency of its own.

## Testing strategy

The suite runs requests against a real local `aiohttp` test server rather than mocking a
request library, so the real network stack (headers, status codes, response bodies) is
exercised end to end instead of asserting against a hand-written double of it.
