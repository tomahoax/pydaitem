"""docs/api/openapi.yaml is the single source of the API map: it must hold together.

It is edited by hand, so these tests stand in for the generator it replaced: every reference
resolves, every operation is classified, the counts hold, and the pages that explain it
(entities.md, reference.md) agree with it.
"""

from __future__ import annotations

import re
from typing import Any

from spec_helpers import (
    DOCS,
    known_values,
    operations,
    schema,
    spec,
    system_state,
    table_column,
)


def _refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        found = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        return found + [ref for value in node.values() for ref in _refs(value)]
    if isinstance(node, list):
        return [ref for value in node for ref in _refs(value)]
    return []


def test_it_is_the_openapi_version_it_says() -> None:
    assert spec()["openapi"] == "3.0.3"


def test_every_reference_resolves() -> None:
    for ref in _refs(spec()):
        node: Any = spec()
        for part in ref.removeprefix("#/").split("/"):
            assert part in node, f"unresolved {ref}"
            node = node[part]


def test_the_counts_hold() -> None:
    """78 calls, 29 of them through pydaitem's façade, 30 marked `x-observed`.

    Change these on purpose, when the spec gains or loses an operation.
    """
    ops = operations()
    assert len(ops) == 78
    assert sum(op.spec["x-coverage"] == "facade" for op in ops) == 29
    assert sum(bool(op.spec.get("x-observed")) for op in ops) == 30
    assert len(spec()["components"]["schemas"]) == 159


def test_every_operation_is_identified_classified_and_tagged() -> None:
    tags = {tag["name"] for tag in spec()["tags"]}
    ids = [op.spec["operationId"] for op in operations()]
    assert len(ids) == len(set(ids))
    for op in operations():
        assert op.spec["x-coverage"] in {"facade", "client"}, op.key
        assert op.spec["summary"], op.key
        assert set(op.spec["tags"]) <= tags, op.key


def test_the_retry_policy_is_complete() -> None:
    policy = spec()["info"]["x-retry-policy"]
    assert policy["maxRetries"] == 2
    assert float(policy["delaySeconds"]) == 0.5
    assert all(rule["when"] and rule["then"] for rule in policy["rules"])


def test_panel_states_and_their_rules() -> None:
    state = system_state()
    values = state["x-known-values"]
    assert len(values) == len(set(values)) == 13
    assert set(state["x-exit-delay-values"]) <= set(values)
    assert all(set(pair) <= set(values) for pair in state["x-preset-sequences"])
    assert set(state["x-app-names"]) == set(values)
    assert schema("TopazeConnectResult")["properties"]["systemState"]["type"] == "string"


def test_entities_page_lists_the_same_states() -> None:
    page = (DOCS / "entities.md").read_text(encoding="utf-8")
    assert table_column(page, "Panel states") == system_state()["x-known-values"]


def test_reference_page_explains_the_same_error_codes() -> None:
    codes = known_values("TopazeExceptionMessage", "message")
    assert len(codes) == len(set(codes)) == 29
    page = (DOCS / "reference.md").read_text(encoding="utf-8")
    assert table_column(page, "Server error codes") == codes


def test_reference_page_lists_the_same_command_statuses() -> None:
    page = (DOCS / "reference.md").read_text(encoding="utf-8")
    section = page.split("## Command statuses\n", 1)[1].split("\n## ", 1)[0]
    listed = re.findall(r"^- `([^`]+)`", section, flags=re.M)
    assert listed == known_values("TopazeSystemStateResult", "commandStatus")


def test_every_model_the_entities_page_names_exists() -> None:
    page = (DOCS / "entities.md").read_text(encoding="utf-8")
    named = set(re.findall(r"`(Topaze\w+|SendCommandRequest)`", page))
    assert named, "the entities page names no wire model any more"
    assert named <= set(spec()["components"]["schemas"])


def test_reference_page_explains_the_same_retry_rules() -> None:
    page = (DOCS / "reference.md").read_text(encoding="utf-8")
    section = page.split("## Retries\n", 1)[1].split("\n## ", 1)[0]
    rows = [line.split("|")[1:3] for line in section.splitlines() if line.startswith("| ")]
    listed = [(when.strip(), then.strip()) for when, then in rows[1:]]  # past the header
    rules = spec()["info"]["x-retry-policy"]["rules"]
    assert listed == [(rule["when"], rule["then"]) for rule in rules]


def test_shared_parameters_and_responses_stay_factored() -> None:
    """A parameter or a response the spec defines once is never written out again inline."""
    components = spec()["components"]
    shared_params = {(p["in"], p["name"]) for p in components["parameters"].values()}
    shared_responses = [r for r in components["responses"].values() if "content" not in r]
    for path, item in spec()["paths"].items():
        methods = [item[m] for m in ("get", "post", "put", "patch", "delete") if m in item]
        for param in item.get("parameters", []) + [
            p for op in methods for p in op.get("parameters", [])
        ]:
            assert "$ref" in param or (param["in"], param["name"]) not in shared_params, (
                path,
                param,
            )
        for op in methods:
            for code, response in op.get("responses", {}).items():
                assert response not in shared_responses, (path, code)
        # What every operation of the path takes belongs to the path.
        if len(methods) > 1:
            common = [
                p
                for p in methods[0].get("parameters", [])
                if all(p in op.get("parameters", []) for op in methods[1:])
            ]
            assert not common, (path, common)
