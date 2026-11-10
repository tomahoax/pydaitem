"""Reading docs/api/openapi.yaml, the single source of the API map, for the tests."""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from typing import Any, NamedTuple

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs" / "api"
SPEC = DOCS / "openapi.yaml"
METHODS = ("get", "post", "put", "patch", "delete")


class Operation(NamedTuple):
    method: str
    path: str
    """As written in the spec: relative to the Topaze server, or to its own `servers`."""
    spec: dict[str, Any]

    @property
    def topaze(self) -> bool:
        """Whether it is a Topaze call, rather than a Keycloak one with servers of its own."""
        return "servers" not in self.spec

    @property
    def key(self) -> tuple[str, str]:
        return path_key(self.method, self.path)


@cache
def spec() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load(SPEC.read_text(encoding="utf-8"))
    return data


def operations() -> list[Operation]:
    return [
        Operation(method.upper(), path, op)
        for path, item in spec()["paths"].items()
        for method, op in item.items()
        if method in METHODS
    ]


def path_key(method: str, path: str) -> tuple[str, str]:
    """Method and path with every parameter written `{}`, and without the `/topaze` prefix."""
    if path.startswith("/topaze/"):
        path = path[len("/topaze") :]
    return method.upper(), re.sub(r"\{[^}]+\}", "{}", path)


def schema(name: str) -> dict[str, Any]:
    found: dict[str, Any] = spec()["components"]["schemas"][name]
    return found


def known_values(model: str, field: str) -> list[str]:
    values: list[str] = schema(model)["properties"][field]["x-known-values"]
    return values


def system_state() -> dict[str, Any]:
    found: dict[str, Any] = schema("TopazeSystemStateResult")["properties"]["systemState"]
    return found


def table_column(markdown: str, heading: str) -> list[str]:
    """First column of the table under `## heading`, backticks removed (`""` stays empty)."""
    section = markdown.split(f"## {heading}\n", 1)[1].split("\n## ", 1)[0]
    rows = [line for line in section.splitlines() if line.startswith("| `")]
    return [row.split("|")[1].strip().strip("`").replace('""', "") for row in rows]
