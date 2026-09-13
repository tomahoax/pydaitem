"""Token persistence and credential resolution.

The point of persistence is that a second process start resumes the session instead of
replaying the Keycloak login form, so the tests below check that path explicitly rather
than just the file round-trip.

Unlike the other client tests, the ones below mock `_auth.login`/`_auth.refresh` directly
instead of a local server: what is under test is `ensure_token`'s own choice between the
two, not their HTTP behaviour, which is already covered elsewhere.
"""

from __future__ import annotations

import stat
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from pydaitem import (
    Credentials,
    DaitemAuthError,
    DaitemClient,
    FileTokenStore,
    MemoryTokenStore,
    MissingCredentials,
    resolve_credentials,
)

# -- File store ---------------------------------------------------------------


async def test_file_store_round_trip(tmp_path: Path) -> None:
    store = FileTokenStore(tmp_path / "token.json")
    assert await store.load() is None

    await store.save("the-refresh-token")
    assert await store.load() == "the-refresh-token"


async def test_file_store_is_owner_only(tmp_path: Path) -> None:
    """The refresh token is a credential at rest, so the file must not be readable."""
    path = tmp_path / "token.json"
    await FileTokenStore(path).save("secret")

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600, f"expected 0600, got {mode:o}"


async def test_file_store_creates_missing_directories(tmp_path: Path) -> None:
    store = FileTokenStore(tmp_path / "nested" / "dir" / "token.json")
    await store.save("token")
    assert await store.load() == "token"


async def test_file_store_clears_on_none(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    store = FileTokenStore(path)
    await store.save("token")

    await store.save(None)
    assert not path.exists()
    assert await store.load() is None


async def test_corrupt_file_degrades_instead_of_raising(tmp_path: Path) -> None:
    """A damaged store must fall back to a full login, never break authentication."""
    path = tmp_path / "token.json"
    path.write_text("{ this is not json", encoding="utf-8")

    assert await FileTokenStore(path).load() is None


async def test_file_without_token_key_returns_none(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text('{"something_else": 1}', encoding="utf-8")
    assert await FileTokenStore(path).load() is None


# -- Client integration -------------------------------------------------------


def _client(store) -> DaitemClient:
    return DaitemClient("account@example.test", "password", token_store=store)


async def test_stored_token_avoids_the_login_form() -> None:
    """The whole point: with a stored token, the login form is never touched."""
    client = _client(MemoryTokenStore("stored-refresh"))

    async def fake_refresh() -> None:
        client._state.access_token = "fresh"
        client._state.token_expires_at = time.monotonic() + 1800

    with (
        patch.object(client._auth, "login", AsyncMock()) as login,
        patch.object(client._auth, "refresh", AsyncMock(side_effect=fake_refresh)) as refresh,
    ):
        await client._auth.ensure_token()

    refresh.assert_awaited_once()
    login.assert_not_awaited()
    await client.close()


async def test_rejected_stored_token_falls_back_to_login() -> None:
    """A stored token can expire on Keycloak's own session cap; that must not raise."""
    client = _client(MemoryTokenStore("stale-refresh"))

    async def fake_login() -> None:
        client._state.access_token = "fresh"
        client._state.token_expires_at = time.monotonic() + 1800

    with (
        patch.object(client._auth, "login", AsyncMock(side_effect=fake_login)) as login,
        patch.object(client._auth, "refresh", AsyncMock(side_effect=DaitemAuthError("expired"))),
    ):
        await client._auth.ensure_token()

    login.assert_awaited_once()
    await client.close()


async def test_empty_store_logs_in() -> None:
    client = _client(MemoryTokenStore(None))

    async def fake_login() -> None:
        client._state.access_token = "fresh"
        client._state.token_expires_at = time.monotonic() + 1800

    with (
        patch.object(client._auth, "login", AsyncMock(side_effect=fake_login)) as login,
        patch.object(client._auth, "refresh", AsyncMock()) as refresh,
    ):
        await client._auth.ensure_token()

    login.assert_awaited_once()
    refresh.assert_not_awaited()
    await client.close()


async def test_token_is_persisted_after_exchange() -> None:
    store = MemoryTokenStore()
    client = _client(store)

    await client._auth._store_tokens(
        {"access_token": "a", "refresh_token": "r", "expires_in": 1800}
    )

    assert await store.load() == "r"
    await client.close()


async def test_valid_token_skips_authentication_entirely() -> None:
    client = _client(MemoryTokenStore("stored"))
    client._state.access_token = "still-valid"
    client._state.token_expires_at = time.monotonic() + 1800

    with (
        patch.object(client._auth, "login", AsyncMock()) as login,
        patch.object(client._auth, "refresh", AsyncMock()) as refresh,
    ):
        await client._auth.ensure_token()

    login.assert_not_awaited()
    refresh.assert_not_awaited()
    await client.close()


# -- Credential resolution ----------------------------------------------------


def test_resolve_prefers_arguments(monkeypatch) -> None:
    monkeypatch.setenv("DAITEM_EMAIL", "env@example.test")
    creds = resolve_credentials(email="arg@example.test", password="p", code="1234")
    assert creds.email == "arg@example.test"


def test_resolve_falls_back_to_environment(monkeypatch) -> None:
    monkeypatch.setenv("DAITEM_EMAIL", "env@example.test")
    monkeypatch.setenv("DAITEM_PASSWORD", "envpass")
    monkeypatch.setenv("DAITEM_MASTER_CODE", "0000")
    creds = resolve_credentials()
    assert creds == Credentials(email="env@example.test", password="envpass", code="0000")


def test_resolve_reads_env_file_last(tmp_path: Path, monkeypatch) -> None:
    for key in ("DAITEM_EMAIL", "DAITEM_PASSWORD", "DAITEM_MASTER_CODE", "DAITEM_SYSTEM_ID"):
        monkeypatch.delenv(key, raising=False)
    env = tmp_path / ".env"
    env.write_text(
        "# comment\n"
        'DAITEM_EMAIL="file@example.test"\n'
        "DAITEM_PASSWORD=filepass\n"
        "DAITEM_MASTER_CODE=4321\n"
        "DAITEM_SYSTEM_ID=42\n",
        encoding="utf-8",
    )
    creds = resolve_credentials(env_file=env)
    assert creds.email == "file@example.test"
    assert creds.password == "filepass"
    assert creds.system_id == 42


def test_resolve_names_what_is_missing(monkeypatch) -> None:
    for key in ("DAITEM_EMAIL", "DAITEM_PASSWORD", "DAITEM_MASTER_CODE"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(MissingCredentials) as excinfo:
        resolve_credentials()
    assert "DAITEM_EMAIL" in str(excinfo.value)


def test_credentials_repr_hides_secrets() -> None:
    creds = Credentials(email="a@b.c", password="hunter2", code="1234")
    rendered = repr(creds)
    assert "hunter2" not in rendered
    assert "1234" not in rendered
