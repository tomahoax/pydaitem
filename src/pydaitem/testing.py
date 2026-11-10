"""Test helpers for code that uses pydaitem: a fake Daitem service, and model factories.

`FakeDaitem` serves the sign-in and the calls the façade makes on a local port, with the
behaviour that matters to a consumer: one panel session at a time, a state that cannot be
read without one, the alarm code, the transmitter, the exit delay. A real `DaitemClient`
talks to it unchanged, so a test exercises the library as it runs in production, edge
cases included::

    async with FakeDaitem() as fake:
        async with fake.client() as client:
            system = DaitemSystem(client, fake.system_id, fake.code)
            fake.held_by = "Phone"  # the mobile app holds the panel
            with pytest.raises(DaitemSessionBusyError):
                await system.commands.arm_away()

Only the reads and commands of the façade's core are served (panel, inventory, capabilities,
commands, transmitter, and empty automations, cameras, clips and scenarios). Anything else
answers 404. It needs nothing beyond `aiohttp`, which pydaitem already depends on.

`status()` builds a `SystemStatus` in a given `PanelState`, for a test that mocks the façade
instead.

Not covered by the stability promise before 1.0.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Self

from aiohttp import web

from .client import DaitemClient
from .const import RAW_TO_PANEL_STATE, REALM, REDIRECT_URI, PanelState
from .models import Group, SystemStatus
from .tokens import TokenStore

__all__ = ["FakeDaitem", "status"]

_AUTH = f"/realms/{REALM}/protocol/openid-connect/auth"
_FORM = f"/realms/{REALM}/login-actions/authenticate"
_TOKEN = f"/realms/{REALM}/protocol/openid-connect/token"
_LOGOUT = f"/realms/{REALM}/protocol/openid-connect/logout"

#: Raw state while each arming runs its exit delay, and once it has settled.
_PRESET_STATES = {
    "partial_arming_name_presence": ("tempo", "presence"),
    "partial_arming_name_1": ("tempo1", "partial1"),
    "partial_arming_name_2": ("tempo2", "partial2"),
}


def status(panel_state: PanelState, *, groups: Sequence[int] = ()) -> SystemStatus:
    """A `SystemStatus` reading as `panel_state`, with `groups` active.

    `PanelState.TRIGGERED` has no known raw value yet, so it cannot be built.
    """
    if panel_state is PanelState.UNKNOWN:
        raw = ""
    else:
        found = [raw for raw, mapped in RAW_TO_PANEL_STATE.items() if mapped is panel_state]
        if not found:
            raise ValueError(f"no raw state is known for {panel_state}")
        raw = str(found[0])
    return SystemStatus(
        state=raw,
        groups=[Group(id=gid, active=True) for gid in groups],
        raw={"systemState": raw, "groups": [{"id": g, "active": True} for g in groups]},
    )


@dataclass
class _Failure:
    method: str
    path_suffix: str
    times: int
    status: int = 500
    message: str | None = None
    details: str | None = None
    drop: bool = False
    stall: bool = False


@dataclass
class FakeDaitem:
    """A local Daitem service for tests: Keycloak sign-in and the Topaze API.

    Every attribute below can be changed while a test runs, to put the panel in the
    situation under test.
    """

    email: str = "user@example.test"
    password: str = "password"
    code: str = "1234"
    """The alarm code the panel accepts."""
    system_id: int = 123456
    system_name: str = "Home"
    owner: bool = True

    state: str = "off"
    """Raw `systemState`. Read it through `SystemStatus.panel_state` in assertions."""
    groups: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"id": 1, "name": "Ground floor", "active": False},
            {"id": 2, "name": "First floor", "active": False},
        ]
    )
    presets: list[str] = field(default_factory=lambda: ["partial_arming_name_presence"])
    """Partial arming presets the installer defined, by the app's item name."""
    exit_delay: float = 0.0
    """Seconds an arming stays in its exit delay. 0 settles at once."""
    latency: float = 0.0
    """Seconds every answer waits before it is sent, as a slow network would."""
    command_status: str = "CMD_OK"
    """What the panel answers to the next commands, `CMD TIMEOUT` for instance."""
    held_by: str | None = None
    """Another device holding the panel session: connecting fails with 409, reading works."""
    online: bool = True
    """False: the transmitter is unreachable, so is the panel."""
    inventory: dict[str, Any] = field(
        default_factory=lambda: {
            "central": {"serialNumber": "CENTRAL-0001", "type": "INTRUSION", "anomalies": {}},
            "genericSensors": {
                "sensors": [
                    {
                        "index": 1,
                        "name": "Front door",
                        "serialNumber": "SENSOR-0001",
                        "type": "MAGNETIC",
                        "group": 1,
                        "anomalies": {"powerSupplyAlert": False},
                    }
                ]
            },
        }
    )

    requests: list[str] = field(default_factory=list, init=False)
    """Every request served, as `METHOD /path`, sign-in included."""
    session_open: bool = field(default=False, init=False)
    """Whether the client under test holds the panel session right now."""
    sessions_opened: int = field(default=0, init=False)
    """How many panel sessions the client opened: each one kept the mobile app out."""
    url: str = field(default="", init=False)
    """Base address of the service, for `api_base` and `auth_base`."""

    _failures: list[_Failure] = field(default_factory=list, init=False, repr=False)
    _unstall: asyncio.Event | None = field(default=None, init=False, repr=False)
    _access_tokens: set[str] = field(default_factory=set, init=False, repr=False)
    _refresh_tokens: set[str] = field(default_factory=set, init=False, repr=False)
    _settles_at: float | None = field(default=None, init=False, repr=False)
    _settled_state: str = field(default="off", init=False, repr=False)
    _runner: web.AppRunner | None = field(default=None, init=False, repr=False)

    # -- Lifecycle ---------------------------------------------------------------------

    async def __aenter__(self) -> Self:
        self._unstall = asyncio.Event()
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handle)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        host, port = self._runner.addresses[0][:2]
        self.url = f"http://{host}:{port}"
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._unstall is not None:
            self._unstall.set()  # let stalled answers end, or cleanup would wait on them
            await asyncio.sleep(0.01)  # and give them the turn to close their connections
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    def client(
        self,
        *,
        password: str | None = None,
        token_store: TokenStore | None = None,
        timeout: float = 5.0,
        call_timeout: float | None = None,
        max_session_hold: float | None = 120.0,
    ) -> DaitemClient:
        """A real `DaitemClient` signed in against this service, with its account."""
        return DaitemClient(
            self.email,
            self.password if password is None else password,
            api_base=self.url,
            auth_base=self.url,
            token_store=token_store,
            timeout=timeout,
            call_timeout=call_timeout,
            max_session_hold=max_session_hold,
        )

    # -- Levers ------------------------------------------------------------------------

    def fail(
        self,
        method: str,
        path_suffix: str,
        *,
        status: int = 500,
        message: str | None = None,
        details: str | None = None,
        times: int = 1,
    ) -> None:
        """Answer the next `times` requests whose path ends with `path_suffix` with an error.

        `message` is the API's business message, one of `ServerMessage` for a typed error.
        """
        self._failures.append(
            _Failure(method.upper(), path_suffix, times, status, message, details)
        )

    def stall(self, method: str, path_suffix: str, *, times: int = 1) -> None:
        """Never answer the next matching request, as a server that hangs: for timeouts."""
        self._failures.append(_Failure(method.upper(), path_suffix, times, stall=True))

    def drop(self, method: str, path_suffix: str, *, times: int = 1) -> None:
        """Close the connection without answering, as a lost answer looks to the client."""
        self._failures.append(_Failure(method.upper(), path_suffix, times, drop=True))

    def revoke_tokens(self) -> None:
        """Reject every token issued so far, as an expired sign-in: the client signs in again."""
        self._access_tokens.clear()
        self._refresh_tokens.clear()

    # -- Dispatch ----------------------------------------------------------------------

    async def _handle(self, request: web.Request) -> web.StreamResponse:
        path = request.path
        self.requests.append(f"{request.method} {path}")
        if self.latency:
            await asyncio.sleep(self.latency)
        failure = self._take_failure(request.method, path)
        if failure is not None:
            if failure.stall and self._unstall is not None:
                await self._unstall.wait()
                # The client gave up long ago: close its connection, or it outlives the server.
                if request.transport is not None:
                    request.transport.close()
                return web.Response(status=503)
            if failure.drop:
                if request.transport is not None:
                    request.transport.close()
                return web.Response()
            return _error(failure.status, failure.message, failure.details)

        if path.startswith("/realms/"):
            return await self._keycloak(request)
        token = request.headers.get("Authorization", "").removeprefix("Bearer ")
        if token not in self._access_tokens:
            return web.Response(status=401)
        return await self._topaze(request)

    def _take_failure(self, method: str, path: str) -> _Failure | None:
        for failure in self._failures:
            if failure.method == method and path.endswith(failure.path_suffix):
                failure.times -= 1
                if failure.times <= 0:
                    self._failures.remove(failure)
                return failure
        return None

    # -- Keycloak ----------------------------------------------------------------------

    async def _keycloak(self, request: web.Request) -> web.StreamResponse:
        if request.method == "GET" and request.path == _AUTH:
            action = f"{self.url}{_FORM}?session_code=fake"
            page = f'<html><body><form id="kc-form-login" action="{action}" method="post">'
            return web.Response(text=page + "</form></body></html>", content_type="text/html")
        if request.method == "POST" and request.path == _FORM:
            form = await request.post()
            if form.get("username") != self.email or form.get("password") != self.password:
                # Keycloak shows the form again, with no redirect to the app.
                return web.Response(text="<html>Invalid</html>", content_type="text/html")
            return web.Response(status=302, headers={"Location": f"{REDIRECT_URI}?code=fake"})
        if request.method == "POST" and request.path == _TOKEN:
            form = await request.post()
            grant = form.get("grant_type")
            if grant == "refresh_token" and form.get("refresh_token") not in self._refresh_tokens:
                return web.json_response({"error": "invalid_grant"}, status=400)
            return web.json_response(self._issue_tokens())
        if request.method == "POST" and request.path == _LOGOUT:
            return web.Response(status=204)
        return web.Response(status=404)

    def _issue_tokens(self) -> dict[str, Any]:
        access, refresh = secrets.token_hex(8), secrets.token_hex(8)
        self._access_tokens.add(access)
        self._refresh_tokens.add(refresh)
        return {"access_token": access, "refresh_token": refresh, "expires_in": 1800}

    # -- Topaze ------------------------------------------------------------------------

    async def _topaze(self, request: web.Request) -> web.StreamResponse:
        method, path = request.method, request.path
        sid = self.system_id
        body = await request.json() if request.can_read_body else None
        routes: dict[tuple[str, str], Any] = {
            ("GET", "/topaze/v5/systems"): lambda: web.json_response(
                [{"id": sid, "name": self.system_name, "role": 1 if self.owner else 0}]
            ),
            ("GET", "/topaze/v1/user"): lambda: web.json_response(
                {"userId": 1, "email": self.email}
            ),
            ("GET", f"/topaze/v5/systems/{sid}/state"): self._read_state,
            ("POST", f"/topaze/v5/systems/{sid}/connect"): lambda: self._connect(body),
            ("POST", f"/topaze/v5/systems/{sid}/disconnect"): self._disconnect,
            ("POST", "/topaze/authenticate/keepAlive"): self._keep_alive,
            ("GET", f"/topaze/v2/systems/{sid}/configuration"): lambda: web.json_response(
                self.inventory
            ),
            ("GET", f"/topaze/v1/widgets/systems/{sid}/users/1"): self._widgets,
            ("POST", f"/topaze/v1/action/systems/{sid}/sendSystemCommand"): lambda: (
                self._command("tempo", "on") if (body or {}).get("active") else self._disarm()
            ),
            ("POST", f"/topaze/v1/action/systems/{sid}/sendGroupCommand"): lambda: (
                self._group_command(body)
            ),
            ("POST", "/topaze/configuration/getConfiguration"): lambda: web.json_response(
                {"transmitterId": "TRANSMITTER-0001"}
            ),
            ("POST", "/topaze/installation/isConnected"): lambda: web.json_response(
                {"isConnected": self.online}
            ),
            ("GET", f"/topaze/v5/systems/{sid}/automatisms"): lambda: web.json_response([]),
            ("GET", f"/topaze/v1/systems/{sid}/cameras"): lambda: web.json_response([]),
            ("GET", f"/topaze/v6/systems/{sid}/videos"): lambda: web.json_response([]),
            ("GET", f"/topaze/v6/systems/{sid}/scenarios"): lambda: web.json_response([]),
        }
        handler = routes.get((method, path))
        if handler is not None:
            return await _respond(handler())
        prefix = f"/topaze/v1/action/systems/{sid}/startPartialArmingWidgetCommand/"
        if method == "POST" and path.startswith(prefix):
            return self._partial(path.removeprefix(prefix))
        return web.Response(status=404)

    def _payload(self) -> dict[str, Any]:
        if self._settles_at is not None and time.monotonic() >= self._settles_at:
            self.state, self._settles_at = self._settled_state, None
        return {"systemState": self.state, "groups": self.groups}

    def _read_state(self) -> web.Response:
        if not self.online:
            return _error(500, "transmitter.error.ttdisconnected")
        if not (self.session_open or self.held_by):
            return _error(403, "status.nottmsessionid", "Failed to get last TTM session")
        return web.json_response(self._payload())

    def _connect(self, body: Any) -> web.Response:
        if not self.online:
            return _error(500, "transmitter.connection.error")
        if self.held_by or self.session_open:
            return _error(409, "transmitter.connection.sessionalreadyopen", self.held_by or "")
        if not isinstance(body, dict) or body.get("masterCode") != self.code:
            return _error(500, "transmitter.connection.badpincode")
        self.session_open = True
        self.sessions_opened += 1
        return web.json_response({"ttmSessionId": "fake-session", **self._payload()})

    def _disconnect(self) -> web.Response:
        self.session_open = False
        return web.json_response({})

    def _keep_alive(self) -> web.Response:
        if not self.session_open:
            return web.Response(status=403)
        return web.json_response({})

    def _widgets(self) -> web.Response:
        items = [{"id": index, "name": name} for index, name in enumerate(self.presets)]
        widget = {"widgetType": "widget_type_partial_arming", "widgetItems": items}
        return web.json_response({"widgets": [widget]})

    def _command_answer(self) -> web.Response:
        if not self.session_open:
            return _error(403, "status.nottmsessionid", "Failed to get last TTM session")
        return web.json_response({**self._payload(), "commandStatus": self.command_status})

    def _command(self, running: str, settled: str) -> web.Response:
        if self.session_open and self.command_status == "CMD_OK":
            if self.exit_delay > 0:
                self.state, self._settled_state = running, settled
                self._settles_at = time.monotonic() + self.exit_delay
            else:
                self.state, self._settles_at = settled, None
        return self._command_answer()

    def _disarm(self) -> web.Response:
        if self.session_open and self.command_status == "CMD_OK":
            self.state, self._settles_at = "off", None
            for group in self.groups:
                group["active"] = False
        return self._command_answer()

    def _group_command(self, body: Any) -> web.Response:
        wanted = {g["id"]: g["active"] for g in (body or {}).get("groups", [])}
        if self.session_open and self.command_status == "CMD_OK":
            for group in self.groups:
                group["active"] = wanted.get(group["id"], group["active"])
            if any(group["active"] for group in self.groups):
                return self._command("tempogroup", "group")
            self.state, self._settles_at = "off", None
        return self._command_answer()

    def _partial(self, index: str) -> web.Response:
        try:
            running, settled = _PRESET_STATES[self.presets[int(index)]]
        except (ValueError, IndexError, KeyError):
            return _error(500, "error.unknown.preset")
        return self._command(running, settled)


async def _respond(answer: Any) -> web.StreamResponse:
    if asyncio.iscoroutine(answer):
        answer = await answer
    response: web.StreamResponse = answer
    return response


def _error(status: int, message: str | None, details: str | None = None) -> web.Response:
    body: dict[str, Any] = {}
    if message is not None:
        body["message"] = message
    if details is not None:
        body["details"] = details
    return web.json_response(body, status=status)
