"""Smaller safeguards: terminal output, sign-out, the env file, server text and the
sign-in server's outages."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import (
    DaitemApiError,
    DaitemClient,
    DaitemConnectionError,
    MemoryTokenStore,
    resolve_credentials,
)
from pydaitem.cli import main
from pydaitem.cli.exit_codes import EXIT_INTERRUPTED, EXIT_OK
from pydaitem.cli.output import _emit, _printable
from pydaitem.client.transport import api_error
from pydaitem.const import REALM
from pydaitem.credentials import read_env_file

TOKEN_PATH = f"/realms/{REALM}/protocol/openid-connect/token"
LOGOUT_PATH = f"/realms/{REALM}/protocol/openid-connect/logout"


# -- Terminal output -------------------------------------------------------------------


def test_control_characters_never_reach_the_terminal() -> None:
    """A scenario named with escape codes could rewrite the confirmation prompt."""
    assert _printable("Night\r\x1b[2KHarmless‮") == "Night��[2KHarmless�"
    assert _printable("Porte d'entrée\tok") == "Porte d'entrée\tok"


def test_text_output_is_cleaned_and_json_untouched(capsys: pytest.CaptureFixture[str]) -> None:
    _emit({"name": "a\x1bb"}, ["a\x1bb"], as_json=False)
    assert capsys.readouterr().out == "a�b\n"
    _emit({"name": "a\x1bb"}, ["a\x1bb"], as_json=True)
    assert json.loads(capsys.readouterr().out) == {"name": "a\x1bb"}


def test_ctrl_c_exits_with_130(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for key, value in {
        "DAITEM_EMAIL": "a@example.test",
        "DAITEM_PASSWORD": "p",
        "DAITEM_MASTER_CODE": "1",
    }.items():
        monkeypatch.setenv(key, value)

    def interrupted(coroutine: object) -> int:
        coroutine.close()  # type: ignore[attr-defined]
        raise KeyboardInterrupt

    with patch("pydaitem.cli.app.asyncio.run", interrupted):
        assert main(["--token-file", str(tmp_path / "t"), "status"]) == EXIT_INTERRUPTED


# -- Sign-out ------------------------------------------------------------------------------


async def serve(routes: list[tuple[str, str, Callable]]) -> AsyncIterator[str]:
    app = web.Application()
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()
    try:
        yield str(server.make_url("")).rstrip("/")
    finally:
        await server.close()


async def test_logout_revokes_the_stored_token_and_clears_the_store() -> None:
    revoked: list[str] = []

    async def logout(request: web.Request) -> web.Response:
        revoked.append((await request.post())["refresh_token"])  # type: ignore[arg-type]
        return web.Response(status=204)

    async for base in serve([("POST", LOGOUT_PATH, logout)]):
        store = MemoryTokenStore("stored-token")
        async with DaitemClient("a@example.test", "p", auth_base=base, token_store=store) as client:
            await client.logout()
        assert revoked == ["stored-token"]
        assert await store.load() is None


def test_the_logout_command_signs_out(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for key, value in {
        "DAITEM_EMAIL": "a@example.test",
        "DAITEM_PASSWORD": "p",
        "DAITEM_MASTER_CODE": "1",
    }.items():
        monkeypatch.setenv(key, value)
    calls: list[str] = []

    async def fake_logout(_self: DaitemClient) -> None:
        calls.append("logout")

    with patch.object(DaitemClient, "logout", fake_logout):
        code = main(["--json", "--token-file", str(tmp_path / "t"), "logout"])
    assert code == EXIT_OK and calls == ["logout"]
    assert json.loads(capsys.readouterr().out) == {"signed_out": True}


# -- The env file --------------------------------------------------------------------------


def test_env_file_quotes_export_and_permissions(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "export DAITEM_EMAIL=a@example.test\n"
        'DAITEM_PASSWORD="pass\'word"\n'
        "DAITEM_MASTER_CODE=12'\n",
        encoding="utf-8",
    )
    env.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        values = read_env_file(env)
    assert values == {
        "DAITEM_EMAIL": "a@example.test",
        "DAITEM_PASSWORD": "pass'word",
        "DAITEM_MASTER_CODE": "12'",
    }
    assert "readable by other users" in caplog.text
    env.chmod(0o600)
    creds = resolve_credentials(env_file=env)
    assert creds.password == "pass'word"


# -- Server text and outages -------------------------------------------------------------------


def test_the_servers_text_stays_out_of_the_message() -> None:
    err = api_error("POST", "/topaze/x", 500, "", text='{"echo": {"masterCode": "1234"}}')
    assert isinstance(err, DaitemApiError)
    assert "1234" not in str(err) and err.body is not None and "1234" in err.body


async def test_an_outage_of_the_sign_in_server_does_not_replay_the_login() -> None:
    """A 5xx is the server's trouble, not a rejected token: no login form flood."""

    async def down(_request: web.Request) -> web.Response:
        return web.Response(status=503)

    async for base in serve([("POST", TOKEN_PATH, down)]):
        async with DaitemClient("a@example.test", "p", auth_base=base) as client:
            client._state.refresh_token = "rt"
            with pytest.raises(DaitemConnectionError, match="unavailable"):
                await client._auth.refresh()


async def test_a_transient_failure_on_the_stored_token_tries_it_again() -> None:
    attempts: list[str] = []

    async def token(request: web.Request) -> web.Response:
        attempts.append((await request.post())["refresh_token"])  # type: ignore[arg-type]
        if len(attempts) == 1:
            return web.Response(status=503)
        return web.json_response({"access_token": "at", "refresh_token": "rt2"})

    async for base in serve([("POST", TOKEN_PATH, token)]):
        store = MemoryTokenStore("stored")
        async with DaitemClient("a@example.test", "p", auth_base=base, token_store=store) as client:
            with pytest.raises(DaitemConnectionError):
                await client._auth.ensure_token()
            await client._auth.ensure_token()
            assert attempts == ["stored", "stored"]
            assert client._state.access_token == "at"
            assert client._state.token_expires_at > time.monotonic()
