"""docs/api/openapi.yaml (the API map) and pydaitem (what the library does) must agree.

When the app or the library changes, one of these fails and says which side to update.
"""

from __future__ import annotations

import re
from pathlib import Path

from spec_helpers import known_values, operations, path_key, spec, system_state

from pydaitem import CommandStatus, DaitemClient, DaitemSystem, PanelState
from pydaitem.const import RAW_TO_PANEL_STATE, RETRY_DELAY, RETRY_LIMIT, ServerMessage

CLIENT = Path(__file__).resolve().parent.parent / "src" / "pydaitem" / "client"


def test_every_raw_state_of_the_app_is_mapped() -> None:
    assert set(RAW_TO_PANEL_STATE) == set(system_state()["x-known-values"])


def test_exit_delay_states_are_the_apps_own_list() -> None:
    arming = {raw for raw, state in RAW_TO_PANEL_STATE.items() if state is PanelState.ARMING}
    assert arming == set(system_state()["x-exit-delay-values"])


def test_named_presets_move_from_delay_to_armed() -> None:
    for delay, armed in system_state()["x-preset-sequences"]:
        assert RAW_TO_PANEL_STATE[delay] is PanelState.ARMING
        assert RAW_TO_PANEL_STATE[armed] in {PanelState.ARMED_PARTIAL, PanelState.ARMED_PARTIAL_2}


def test_server_messages_are_the_apps_29_codes() -> None:
    assert {m.value for m in ServerMessage} == set(
        known_values("TopazeExceptionMessage", "message")
    )


def test_command_statuses_are_the_apps() -> None:
    expected = set(known_values("TopazeSystemStateResult", "commandStatus"))
    assert {s.value for s in CommandStatus} == expected


def test_retry_rules_are_the_apps() -> None:
    policy = spec()["info"]["x-retry-policy"]
    assert policy["maxRetries"] == RETRY_LIMIT
    assert float(policy["delaySeconds"]) == RETRY_DELAY


#: Calls whose path is not a literal in the client, and where it is built instead.
_BUILT_PATHS = {
    ("GET", "/v5/systems/{}/connect/{}"): "client/panel.py, from the Location header",
    ("GET", "/v5/systems/{}/logbook/{}"): "client/logbook.py, from the Location header",
    ("GET", "/v5/systems/{}/videos/capture/carir/{}/{}"): "client/video.py, job path",
    ("GET", "/v5/systems/{}/videos/{}/{}/{}/mpeg4"): "client/video.py, clip_path",
    ("DELETE", "/v5/systems/{}/videos/{}/{}/{}"): "client/video.py, _clip_base",
    ("POST", "/authenticate/keepAlive"): "client/transport.py, KEEP_ALIVE_PATH",
}

_CALL_RE = re.compile(
    r'request(?:_full|_bytes|_object)?\(\s*"(GET|POST|PUT|PATCH|DELETE)",\s*f?"(/topaze[^"]*)"'
)

#: Alarm commands go through `_Commands._command`, which always POSTs.
_COMMAND_RE = re.compile(r'_command\(\s*f?"(/topaze[^"]*)"')


def _implemented() -> set[tuple[str, str]]:
    source = "\n".join(p.read_text(encoding="utf-8") for p in CLIENT.glob("*.py"))
    return {
        path_key(method, path)
        for method, path in [
            *_CALL_RE.findall(source),
            *(("POST", path) for path in _COMMAND_RE.findall(source)),
        ]
    }


def test_every_call_of_the_app_has_a_client_method() -> None:
    implemented = _implemented() | set(_BUILT_PATHS)
    missing = sorted(op.key for op in operations() if op.topaze and op.key not in implemented)
    assert missing == []


def test_the_client_calls_nothing_the_spec_lacks() -> None:
    mapped = {op.key for op in operations()}
    assert _implemented() - mapped == set()


def test_the_raw_dump_reads_only_calls_the_spec_maps() -> None:
    """`collect_raw` reads some paths directly, out of reach of the client scan above."""
    source = (CLIENT.parent / "system" / "probe.py").read_text(encoding="utf-8")
    read = {path_key("GET", path) for path in re.findall(r'get\(f?"(/topaze[^"]*)"\)', source)}
    assert read, "probe.py reads no path any more: update this test"
    assert read - {op.key for op in operations()} == set()


#: Façade namespaces that are not an API resource, and why.
_FACADE_ONLY = {"capabilities": "what the installation supports, read from the widgets"}


def test_the_facade_is_grouped_like_the_api() -> None:
    """Each namespace of `DaitemSystem` is a resource (a tag) of the API map."""
    system = DaitemSystem(DaitemClient("account@example.test", "password"), 1, "0000")
    namespaces = {
        name
        for name, value in vars(system).items()
        if not name.startswith("_") and not callable(value)
    }
    tags = {tag["name"] for tag in spec()["tags"]}
    assert namespaces - set(_FACADE_ONLY) <= tags
    assert {"panel", "inventory", "commands", "schedule", "automation", "video", "logbook"} <= (
        namespaces
    )
