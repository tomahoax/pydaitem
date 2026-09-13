"""Login flow tests against a real local Keycloak-shaped server.

See test_errors.py for why a local aiohttp server is used instead of a mock library.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

from aiohttp import web
from aiohttp.test_utils import TestServer

from pydaitem import DaitemClient
from pydaitem.const import REALM

AUTH_PATH = f"/realms/{REALM}/protocol/openid-connect/auth"
TOKEN_PATH = f"/realms/{REALM}/protocol/openid-connect/token"
FORM_PATH = "/login-actions/authenticate"


async def token(_request: web.Request) -> web.Response:
    return web.json_response({"access_token": "at", "refresh_token": "rt", "expires_in": 1800})


async def serve(routes: list[tuple[str, str, Callable]]) -> AsyncIterator[DaitemClient]:
    """Start a local Keycloak-shaped server and return a client pointing at it."""
    app = web.Application()
    app.router.add_post(TOKEN_PATH, token)
    for method, path, handler in routes:
        app.router.add_route(method, path, handler)
    server = TestServer(app)
    await server.start_server()

    client = DaitemClient(
        "account@example.test", "password", auth_base=str(server.make_url("")).rstrip("/")
    )
    try:
        yield client
    finally:
        await client.close()
        await server.close()


async def test_login_drives_the_keycloak_form() -> None:
    """The common case: Keycloak serves a login form to submit credentials to."""

    async def auth(request: web.Request) -> web.Response:
        # Keycloak always emits an absolute form action, so build one from the request.
        form_url = request.url.with_path(FORM_PATH).with_query({"session_code": "abc"})
        return web.Response(
            text=(
                f'<html><body><form id="kc-form-login" action="{form_url}" '
                'method="post"></form></body></html>'
            ),
            content_type="text/html",
        )

    async def form_post(_request: web.Request) -> web.Response:
        return web.Response(status=302, headers={"Location": "daitemsecure://auth?code=THE-CODE"})

    routes = [("GET", AUTH_PATH, auth), ("POST", FORM_PATH, form_post)]
    async for client in serve(routes):
        await client.login()
        assert client._state.access_token == "at"
        assert client._state.refresh_token == "rt"


async def test_login_skips_the_form_on_an_active_sso_session() -> None:
    """Keycloak may already recognise the session cookie and redirect straight away.

    Regression: the authorization endpoint's GET followed redirects by default, so a 302
    straight to `daitemsecure://auth?...` (a non-HTTP scheme) crashed the underlying
    aiohttp call instead of being read as an already-issued authorization code.
    """

    async def auth(_request: web.Request) -> web.Response:
        return web.Response(
            status=302,
            headers={"Location": "daitemsecure://auth?session_state=s&code=THE-CODE"},
        )

    async for client in serve([("GET", AUTH_PATH, auth)]):
        await client.login()
        assert client._state.access_token == "at"
        assert client._state.refresh_token == "rt"
