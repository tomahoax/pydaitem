"""Sign-in and token handling that cannot be steered elsewhere, against a real local server.

The password, the tokens and the alarm code must only reach the sign-in server and the API,
and a client must only ever act as the account it was given.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import AsyncIterator, Callable
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from yarl import URL

from pydaitem import DaitemApiError, DaitemAuthError, DaitemClient, FileTokenStore, Remedy
from pydaitem.const import REALM

AUTH_PATH = f"/realms/{REALM}/protocol/openid-connect/auth"
TOKEN_PATH = f"/realms/{REALM}/protocol/openid-connect/token"
FORM_PATH = f"/realms/{REALM}/login-actions/authenticate"
COMMAND_PATH = "/topaze/v1/action/systems/1/sendSystemCommand"


async def good_token(_request: web.Request) -> web.Response:
    return web.json_response({"access_token": "at", "refresh_token": "rt", "expires_in": 1800})


def form_page(action: str | None = None) -> Callable:
    async def auth(request: web.Request) -> web.Response:
        target = action or str(request.url.with_path(FORM_PATH).with_query({"session_code": "a"}))
        return web.Response(
            text=f'<html><form id="kc-form-login" action="{target}" method="post"></form></html>',
            content_type="text/html",
        )

    return auth


def redirect_to(location: str, posted: list[bool] | None = None) -> Callable:
    async def handler(_request: web.Request) -> web.Response:
        if posted is not None:
            posted.append(True)
        return web.Response(status=302, headers={"Location": location})

    return handler


async def serve(
    routes: list[tuple[str, str, Callable]],
    *,
    session: aiohttp.ClientSession | None = None,
    token: Callable = good_token,
) -> AsyncIterator[tuple[DaitemClient, str]]:
    app = web.Application()
    app.router.add_post(TOKEN_PATH, token)
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()
    base = str(server.make_url("")).rstrip("/")
    client = DaitemClient(
        "account@example.test", "password", api_base=base, auth_base=base, session=session
    )
    try:
        yield client, base
    finally:
        await client.close()
        await server.close()


# -- The login form ------------------------------------------------------------


async def test_a_single_sign_on_cookie_in_a_shared_session_is_not_used() -> None:
    """Another account's Keycloak cookie must not sign this client in without a password."""
    posted: list[bool] = []

    async def auth(request: web.Request) -> web.Response:
        if "KEYCLOAK_IDENTITY" in request.cookies:
            return web.Response(status=302, headers={"Location": "daitemsecure://auth?code=SSO"})
        return await form_page()(request)

    routes = [
        ("GET", AUTH_PATH, auth),
        ("POST", FORM_PATH, redirect_to("daitemsecure://auth?code=C", posted)),
    ]
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True)) as shared:
        async for client, base in serve(routes, session=shared):
            shared.cookie_jar.update_cookies(
                {"KEYCLOAK_IDENTITY": "someone-else"}, response_url=URL(base)
            )
            await client.login()
            assert posted == [True]


@pytest.mark.parametrize(
    "action",
    [
        f"https://elsewhere.example{FORM_PATH}",
        "/somewhere/else",
        f"//elsewhere.example{FORM_PATH}",
    ],
)
async def test_a_form_posting_elsewhere_gets_no_password(action: str) -> None:
    posted: list[bool] = []
    routes = [
        ("GET", AUTH_PATH, form_page(action)),
        ("POST", "/somewhere/else", redirect_to("daitemsecure://auth?code=C", posted)),
    ]
    async for client, _ in serve(routes):
        with pytest.raises(DaitemAuthError, match="outside the sign-in server") as raised:
            await client.login()
        assert posted == []
        assert raised.value.remedy is Remedy.RETRY_LATER


async def test_the_keycloak_form_is_preferred_over_another_form() -> None:
    async def auth(request: web.Request) -> web.Response:
        login = request.url.with_path(FORM_PATH)
        return web.Response(
            text=(
                '<form action="/search"></form>'
                f'<form id="kc-form-login" action="{login}" method="post"></form>'
            ),
            content_type="text/html",
        )

    routes = [
        ("GET", AUTH_PATH, auth),
        ("POST", FORM_PATH, redirect_to("daitemsecure://auth?code=C")),
    ]
    async for client, _ in serve(routes):
        await client.login()
        assert client._state.access_token == "at"


@pytest.mark.parametrize(
    ("location", "match"),
    [
        ("daitemsecure://auth?error=access_denied&error_description=blocked", "access_denied"),
        ("https://elsewhere.example/?code=STOLEN", "no authorization code"),
    ],
)
async def test_only_the_apps_redirect_gives_a_code(location: str, match: str) -> None:
    routes = [("GET", AUTH_PATH, redirect_to(location))]
    async for client, _ in serve(routes):
        with pytest.raises(DaitemAuthError, match=match) as raised:
            await client.login()
        # Keycloak did not sign the account in: the password is what to ask for again.
        assert raised.value.remedy is Remedy.ASK_CREDENTIALS


# -- The token endpoint ----------------------------------------------------------


@pytest.mark.parametrize(
    "answer",
    [
        web.Response(text="<html>gateway</html>", content_type="text/html"),
        web.json_response(["at"]),
        web.json_response({"refresh_token": "rt"}),
    ],
)
async def test_an_odd_token_answer_is_an_auth_error(answer: web.Response) -> None:
    async def token(_request: web.Request) -> web.Response:
        return answer

    routes = [("GET", AUTH_PATH, redirect_to("daitemsecure://auth?code=C"))]
    async for client, _ in serve(routes, token=token):
        with pytest.raises(DaitemAuthError) as raised:
            await client.login()
        # The flow went wrong, not the account: asking for the password would not help.
        assert raised.value.remedy is Remedy.RETRY_LATER


async def test_the_token_request_does_not_follow_a_redirect() -> None:
    followed: list[bool] = []

    async def elsewhere(_request: web.Request) -> web.Response:
        followed.append(True)
        return await good_token(_request)

    async def token(_request: web.Request) -> web.Response:
        return web.Response(status=307, headers={"Location": "/elsewhere"})

    routes = [
        ("GET", AUTH_PATH, redirect_to("daitemsecure://auth?code=C")),
        ("POST", "/elsewhere", elsewhere),
    ]
    async for client, _ in serve(routes, token=token):
        with pytest.raises(DaitemAuthError):
            await client.login()
        assert followed == []


# -- API requests ------------------------------------------------------------------


async def test_a_write_does_not_follow_a_redirect() -> None:
    """The alarm code travels in write bodies: a 307 would send it on unchanged."""
    followed: list[bool] = []

    async def elsewhere(_request: web.Request) -> web.Response:
        followed.append(True)
        return web.json_response({})

    async def moved(_request: web.Request) -> web.Response:
        return web.Response(status=307, headers={"Location": "/elsewhere"})

    routes = [("POST", COMMAND_PATH, moved), ("POST", "/elsewhere", elsewhere)]
    async for client, _ in serve(routes):
        _authenticated(client)
        with pytest.raises(DaitemApiError, match="redirect, not followed"):
            await client._transport.request("POST", COMMAND_PATH, json={}, retry=False)
        assert followed == []


async def test_a_token_rejected_twice_is_forgotten() -> None:
    async def rejected(_request: web.Request) -> web.Response:
        return web.json_response({}, status=401)

    routes = [("GET", "/topaze/v1/user", rejected)]
    async for client, _ in serve(routes):
        _authenticated(client)
        with pytest.raises(DaitemAuthError):
            await client.account.get_user()
        assert client._state.access_token is None and client._state.refresh_token is None


def test_plain_http_addresses_are_refused() -> None:
    with pytest.raises(ValueError, match="not an https address"):
        DaitemClient("a@example.test", "p", api_base="http://api.example")
    with pytest.raises(ValueError, match="not an https address"):
        DaitemClient("a@example.test", "p", auth_base="http://auth.example")


async def test_a_failing_token_store_does_not_fail_the_sign_in() -> None:
    class Broken:
        async def load(self) -> str | None:
            return None

        async def save(self, refresh_token: str | None) -> None:
            raise OSError("disk full")

    routes = [("GET", AUTH_PATH, redirect_to("daitemsecure://auth?code=C"))]
    async for client, _ in serve(routes):
        client._state.token_store = Broken()
        await client.login()
        assert client._state.access_token == "at"


# -- The token file ------------------------------------------------------------------


async def test_a_token_saved_for_another_account_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    await FileTokenStore(path, account="home@example.test").save("home-token")
    assert await FileTokenStore(path, account="HOME@example.test").load() == "home-token"
    assert await FileTokenStore(path, account="office@example.test").load() is None


async def test_a_token_saved_without_an_account_is_ignored_when_one_is_given(
    tmp_path: Path,
) -> None:
    """A file from an older version cannot say whose token it holds."""
    path = tmp_path / "token.json"
    await FileTokenStore(path).save("old-token")
    assert await FileTokenStore(path, account="home@example.test").load() is None
    assert await FileTokenStore(path).load() == "old-token"


async def test_a_token_file_that_is_not_an_object_is_ignored(tmp_path: Path) -> None:
    path = tmp_path / "token.json"
    path.write_text("[]", encoding="utf-8")
    path.chmod(0o600)
    assert await FileTokenStore(path).load() is None


async def test_a_token_file_owned_by_another_user_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "token.json"
    await FileTokenStore(path).save("planted")
    monkeypatch.setattr(os, "getuid", lambda: path.stat().st_uid + 1)
    assert await FileTokenStore(path).load() is None


async def test_a_token_file_readable_by_others_is_used_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "token.json"
    await FileTokenStore(path).save("token")
    path.chmod(0o644)
    with caplog.at_level(logging.WARNING):
        assert await FileTokenStore(path).load() == "token"
    assert "readable by other users" in caplog.text


async def test_a_token_file_that_cannot_be_deleted_does_not_break_logout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "token.json"
    store = FileTokenStore(path)
    await store.save("token")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "unlink", refuse)
    await store.save(None)


def _authenticated(client: DaitemClient) -> None:
    client._state.access_token = "token"
    client._state.refresh_token = "refresh"
    client._state.token_expires_at = time.monotonic() + 3600
