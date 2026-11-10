"""CLI commands beyond the alarm: what they write and where their errors go."""

from __future__ import annotations

import argparse
import json
import stat
from pathlib import Path
from typing import Any

import pytest

from pydaitem.cli.exit_codes import EXIT_ERROR, EXIT_OK, EXIT_USAGE
from pydaitem.cli.extras import _cmd_automate, _cmd_dump


class _Automation:
    async def read(self) -> list[Any]:
        return []


class _System:
    """Just enough of `DaitemSystem` for these commands."""

    automation = _Automation()

    async def collect_raw(self, *, logbook_entries: int, redact: bool) -> dict[str, Any]:
        return {"system_id": 1, "payloads": {"state": {"systemState": "off"}}, "errors": {}}


async def test_dump_is_readable_by_its_owner_only(tmp_path: Path) -> None:
    """It holds personal data, like the token file."""
    output = tmp_path / "dump.json"
    output.write_text("old", encoding="utf-8")
    output.chmod(0o644)
    args = argparse.Namespace(output=str(output), logbook=0, json=True, redact=True)
    assert await _cmd_dump(args, _System()) == EXIT_OK  # type: ignore[arg-type]
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert json.loads(output.read_text(encoding="utf-8"))["system_id"] == 1


async def test_unknown_automation_is_reported_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """stdout stays parseable under --json."""
    args = argparse.Namespace(
        id="nope", automation_command="ON", position=None, yes=True, json=True
    )
    assert await _cmd_automate(args, _System()) == EXIT_USAGE  # type: ignore[arg-type]
    out, err = capsys.readouterr()
    assert out == "" and "No automation with id nope" in err


async def test_dump_that_cannot_be_written_is_an_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """After every read has run, a bad --output must not end in a traceback."""
    args = argparse.Namespace(output=str(tmp_path), logbook=0, json=True, redact=True)  # a dir
    assert await _cmd_dump(args, _System()) == EXIT_ERROR  # type: ignore[arg-type]
    assert "Could not write" in capsys.readouterr().err
