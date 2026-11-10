"""Home screen widgets: `client.widgets.*`.

The widgets carry the partial arming presets (see `client.commands.list_presets`) and,
on some installations, automations and scenarios.
"""

from __future__ import annotations

from typing import Any

from .paths import segment
from .transport import _Transport


class _Widgets:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def get(self, system_id: int, user_id: int) -> dict[str, Any]:
        """`{widgets: [{id, widgetType, title, isVisible, widgetItems}]}`."""
        return await self._transport.request_object(
            "GET", f"/topaze/v1/widgets/systems/{system_id}/users/{segment(user_id)}"
        )

    async def save(self, system_id: int, user_id: int, widgets: list[dict[str, Any]]) -> None:
        """Replace the whole widget layout."""
        await self._transport.request(
            "POST",
            f"/topaze/v1/widgets/systems/{system_id}/users/{segment(user_id)}",
            json={"widgets": widgets},
            retry=False,
        )

    async def save_one(self, system_id: int, user_id: int, widget: dict[str, Any]) -> None:
        widget_id = widget["id"]
        await self._transport.request(
            "POST",
            f"/topaze/v1/widgets/{segment(widget_id)}/systems/{system_id}/users/{segment(user_id)}",
            json=widget,
            retry=False,
        )

    async def favorites_popup_shown(self, system_id: int, user_id: int) -> Any:
        return await self._transport.request(
            "GET",
            f"/topaze/v1/systems/{system_id}/users/{segment(user_id)}/isFavoritesMigrationPopupShown",
        )

    async def hide_favorites_popup(self, system_id: int, user_id: int) -> None:
        await self._transport.request(
            "POST",
            f"/topaze/v1/systems/{system_id}/users/{segment(user_id)}/hideFavoritesMigrationPopup",
            retry=False,
        )
