"""Commands that drive a real alarm: `client.commands.*`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..exceptions import DaitemCommandError
from ..models import SystemStatus
from .account import _Account
from .transport import _Transport


class _Commands:
    def __init__(self, transport: _Transport, account: _Account) -> None:
        self._transport = transport
        self._account = account

    async def arm(self, system_id: int) -> SystemStatus:
        """Arm every group."""
        return await self._command(
            f"/topaze/v1/action/systems/{system_id}/sendSystemCommand", {"active": True}
        )

    async def disarm(self, system_id: int) -> SystemStatus:
        """Disarm every group."""
        return await self._command(
            f"/topaze/v1/action/systems/{system_id}/sendSystemCommand", {"active": False}
        )

    async def arm_groups(self, system_id: int, groups: Mapping[int, bool]) -> SystemStatus:
        """Arm or disarm specific groups, e.g. ``{1: True, 2: False}``."""
        payload = {"groups": [{"id": gid, "active": act} for gid, act in groups.items()]}
        return await self._command(
            f"/topaze/v1/action/systems/{system_id}/sendGroupCommand", payload
        )

    async def start_partial_arming(self, system_id: int, preset: int = 0) -> SystemStatus:
        """Trigger a partial arming preset (0 is "presence")."""
        return await self._command(
            f"/topaze/v1/action/systems/{system_id}/startPartialArmingWidgetCommand/{preset}",
            None,
        )

    async def list_presets(self, system_id: int) -> list[dict[str, Any]]:
        """Partial arming presets defined on the installation, from the widgets config.

        Each item carries the `id` to pass to `start_partial_arming` and a `name`
        identifying the preset. Lets a caller discover presets instead of hardcoding them.
        """
        user = await self._account.get_user()
        data = await self._transport.request(
            "GET", f"/topaze/v1/widgets/systems/{system_id}/users/{user['userId']}"
        )
        items: list[dict[str, Any]] = []
        for widget in data.get("widgets") or []:
            if widget.get("widgetType") == "widget_type_partial_arming":
                items.extend(widget.get("widgetItems") or [])
        return items

    async def _command(self, path: str, payload: dict[str, Any] | None) -> SystemStatus:
        kwargs: dict[str, Any] = {"json": payload} if payload is not None else {}
        # Never retried: a replay could arm or disarm the alarm twice.
        data = await self._transport.request("POST", path, retry=False, **kwargs)
        status = SystemStatus.from_json(data)
        if status.command_status and status.command_status != "CMD_OK":
            raise DaitemCommandError(f"command rejected: {status.command_status}")
        return status
