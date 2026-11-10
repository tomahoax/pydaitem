"""Shared, immutable state: the client, the installation id and the alarm code."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import AbstractAsyncContextManager
from contextvars import ContextVar
from typing import Any, Concatenate, ParamSpec, Protocol, TypeVar

from ..client import DaitemClient
from ..exceptions import DaitemConnectionError, Remedy
from ..models import SystemStatus

_T = TypeVar("_T")
_P = ParamSpec("_P")


class _Sent:
    """Whether the write of the call under way has left: set just before it does."""

    def __init__(self) -> None:
        self.value = False


#: Shared by nested budgets (`arm_away` calls `arm`): the outer one expires first, and must
#: still know the command left.
_SENT: ContextVar[_Sent | None] = ContextVar("pydaitem_write_sent", default=None)


class _SystemState:
    def __init__(self, client: DaitemClient, system_id: int, code: str) -> None:
        """`code` is the alarm code of the account in use, not necessarily the master."""
        self.client = client
        self.system_id = system_id
        self.code = code
        # Work a read does while it holds a session it had to open anyway (a blocked
        # arming mode discovery), set by DaitemSystem. Never raises.
        self.in_read_session: Callable[[], Awaitable[None]] | None = None
        self._reads: dict[str, asyncio.Future[Any]] = {}
        self._kept: dict[str, tuple[float, Any]] = {}

    def keep(self, key: str, value: Any) -> None:
        """Remember the latest answer of a read, for callers that accept one a little old."""
        self._kept[key] = (time.monotonic(), value)

    def kept(self, key: str, max_age: float) -> Any:
        """The answer kept for `key` if it is at most `max_age` seconds old, else None."""
        if max_age <= 0 or key not in self._kept:
            return None
        at, value = self._kept[key]
        return value if time.monotonic() - at <= max_age else None

    @contextlib.asynccontextmanager
    async def deadline(self, what: str) -> AsyncIterator[None]:
        """Bound a façade call by the client's `call_timeout`, when one is set.

        Past it the call raises `DaitemConnectionError`, never a `TimeoutError`: its remedy
        is `CHECK_STATE` when a write already left (see `sending`), `RETRY_LATER` otherwise.
        Waiting for the panel lock counts, and a panel session opened meanwhile is still
        released.
        """
        sent = _SENT.get()
        token = None
        if sent is None:
            sent = _Sent()
            token = _SENT.set(sent)
        try:
            timeout = self.client._state.call_timeout
            if timeout is None:
                yield
                return
            try:
                async with asyncio.timeout(timeout):
                    yield
            except TimeoutError as err:
                remedy = Remedy.CHECK_STATE if sent.value else None
                raise DaitemConnectionError(
                    f"{what}: no answer within {timeout:g} s", remedy=remedy
                ) from err
        finally:
            if token is not None:
                _SENT.reset(token)

    async def sending(self, write: Awaitable[_T]) -> _T:
        """Await `write`, a command or another write, marking it as having left first."""
        sent = _SENT.get()
        if sent is not None:
            sent.value = True
        return await write

    async def shared(self, key: str, read: Callable[[], Awaitable[_T]]) -> _T:
        """Run `read`, or join the same read already running: concurrent callers share one.

        A poll, an action and a diagnostics download that land together send one request,
        not three. Reads only, never a write. A caller cancelled meanwhile leaves the read
        running for the others. A caller that holds the panel runs its read itself: the
        shared one would wait for a panel lock that caller is not going to give up.
        """
        if asyncio.current_task() is self.client.panel._owner:
            return await read()
        running = self._reads.get(key)
        if running is None:
            running = asyncio.ensure_future(read())
            self._reads[key] = running
            running.add_done_callback(lambda task: self._forget(key, task))
        result: _T = await asyncio.shield(running)
        return result

    def _forget(self, key: str, task: asyncio.Future[Any]) -> None:
        if self._reads.get(key) is task:
            del self._reads[key]
        if not task.cancelled():
            task.exception()  # retrieved, so a read every caller left fails without a warning

    def session(self) -> AbstractAsyncContextManager[SystemStatus]:
        """A panel session on this installation, released when the block ends."""
        return self.client.panel.session(self.system_id, self.code)


class _HasState(Protocol):
    _state: _SystemState


_S = TypeVar("_S", bound=_HasState)


def bounded(
    what: str,
) -> Callable[
    [Callable[Concatenate[_S, _P], Awaitable[_T]]],
    Callable[Concatenate[_S, _P], Coroutine[Any, Any, _T]],
]:
    """Apply the client's `call_timeout` to a façade method, as `_SystemState.deadline`."""

    def wrap(
        method: Callable[Concatenate[_S, _P], Awaitable[_T]],
    ) -> Callable[Concatenate[_S, _P], Coroutine[Any, Any, _T]]:
        @functools.wraps(method)
        async def run(self: _S, /, *args: _P.args, **kwargs: _P.kwargs) -> _T:
            async with self._state.deadline(what):
                return await method(self, *args, **kwargs)

        return run

    return wrap
