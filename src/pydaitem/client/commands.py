"""Commands that drive a real alarm: `client.commands.*`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..const import CommandStatus
from ..const.devices import PpmsAlert
from ..exceptions import DaitemApiError, DaitemCommandError
from ..models import SystemStatus
from ..models._shared import dicts, parse
from .account import _Account
from .paths import segment
from .transport import _Transport
from .widgets import _Widgets


class _Commands:
    def __init__(self, transport: _Transport, account: _Account, widgets: _Widgets) -> None:
        self._transport = transport
        self._account = account
        self._widgets = widgets
        self._user_id: Any = None

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
            f"/topaze/v1/action/systems/{system_id}/startPartialArmingWidgetCommand/{segment(preset)}",
            None,
        )

    async def start_scenario(self, system_id: int, scenario_id: int) -> SystemStatus:
        """Run a scenario. WARNING: it may disarm the alarm among its actions."""
        return await self._command(
            f"/topaze/v1/action/systems/{system_id}/startScenarioWidgetCommand/{segment(scenario_id)}",
            None,
        )

    async def start_alert(self, system_id: int, alert_id: int) -> SystemStatus:
        """WARNING: triggers a real alert (audible, silent or fire), as a panic button does."""
        return await self._command(
            f"/topaze/v1/action/systems/{system_id}/startAlertWidgetCommand/{segment(alert_id)}",
            None,
        )

    async def send_ppms(self, system_id: int, alert: PpmsAlert, active: bool) -> None:
        """WARNING: starts or stops a safety plan alert (professional sites)."""
        await self._transport.request(
            "POST",
            f"/topaze/v1/systems/{system_id}/actions/sendPpmsCommand",
            json={"type": str(alert), "status": "ON" if active else "OFF"},
            retry=False,
        )

    async def list_presets(self, system_id: int) -> list[dict[str, Any]]:
        """Partial arming presets defined on the installation, from the widgets config.

        Each item carries the `id` to pass to `start_partial_arming` and a `name`
        identifying the preset. Lets a caller discover presets instead of hardcoding them.
        """
        if self._user_id is None:
            # The account's own id: read once, it does not change while the client lives.
            user = await self._account.get_user()
            self._user_id = user.get("userId")
            if self._user_id is None:
                raise DaitemApiError("the user profile carries no userId")
        data = await self._widgets.get(system_id, self._user_id)
        items: list[dict[str, Any]] = []
        for widget in dicts(data, "widgets"):
            if widget.get("widgetType") == "widget_type_partial_arming":
                items.extend(dicts(widget.get("widgetItems")))
        return items

    async def _command(self, path: str, payload: dict[str, Any] | None) -> SystemStatus:
        kwargs: dict[str, Any] = {"json": payload} if payload is not None else {}
        # Never retried: a replay could arm or disarm the alarm twice.
        data = await self._transport.request_object("POST", path, retry=False, **kwargs)
        status = parse(lambda: SystemStatus.from_json(data), "command")
        if status.command_status and status.command_status != CommandStatus.OK:
            reason = _COMMAND_FAILURES.get(status.command_status, "command rejected")
            raise DaitemCommandError(
                f"{reason} ({status.command_status})", command_status=status.command_status
            )
        return status


#: What each failed command status means, worded for a log line or an error message.
_COMMAND_FAILURES: dict[str, str] = {
    CommandStatus.TIMEOUT: "the panel did not confirm the command in time, it may still have run",
    CommandStatus.UNKNOWN: "the panel does not know this command",
    CommandStatus.FORBIDDEN: "the panel refused the command for this account",
}
