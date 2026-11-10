"""Account and systems: `client.account.*`."""

from __future__ import annotations

from typing import Any

from ..models import Inventory, System
from ..models._shared import dicts, parse
from .paths import segment
from .transport import _Transport


class _Account:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def get_user(self) -> dict[str, Any]:
        return await self._transport.request_object("GET", "/topaze/v1/user")

    async def list_systems(self) -> list[System]:
        data = await self._transport.request("GET", "/topaze/v5/systems")
        return parse(lambda: [System.from_json(item) for item in dicts(data)], "systems")

    async def get_inventory(self, system_id: int) -> Inventory:
        """Device inventory. Does not include live open/closed detector state."""
        data = await self._transport.request_object(
            "GET", f"/topaze/v2/systems/{system_id}/configuration"
        )
        return parse(lambda: Inventory.from_json(data), "inventory")

    async def topaze_logout(self, id_token: str | None = None, *, v2: bool = True) -> None:
        """Log the app session out of Topaze. Keycloak's own logout is `client.logout()`.

        The id token goes out under both `idToken` and `id_token`, as the app sends it.
        """
        body = {"idToken": id_token, "id_token": id_token}
        # Each path stays a literal at its call: tests match them against the API map.
        if v2:
            await self._transport.request(
                "POST", "/topaze/v2/authenticate/logout", json=body, retry=False
            )
        else:
            await self._transport.request(
                "POST", "/topaze/authenticate/logout", json=body, retry=False
            )

    async def upsell(self, lang: str = "en") -> dict[str, Any]:
        """Marketing message the app shows, by language."""
        return await self._transport.request_object("GET", f"/topaze/v5/upsell/{segment(lang)}")

    async def send_feedback(self, user_id: int, message: str) -> dict[str, Any]:
        return await self._transport.request_object(
            "POST",
            f"/topaze/v6/users/{segment(user_id)}/feedback",
            json={"message": message},
            retry=False,
        )
