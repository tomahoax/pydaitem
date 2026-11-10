"""Push registration, alert receivers and contacts: `client.notifications.*`.

Push goes through the app's own push service, so registering a device here only matters to
a client that can receive those pushes.
"""

from __future__ import annotations

from typing import Any

from ..models._shared import dicts
from .paths import segment
from .transport import _Transport


class _Notifications:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def register_push(
        self,
        system_id: int,
        device_id: str,
        *,
        lang: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {"deviceId": device_id}
        if lang is not None:
            payload["lang"] = lang
        if user_agent is not None:
            payload["userAgent"] = user_agent
        await self._transport.request(
            "POST", f"/topaze/v5/systems/{system_id}/notifications", json=payload, retry=False
        )

    async def unregister_push(self, system_id: int, device_id: str) -> None:
        await self._transport.request(
            "DELETE",
            f"/topaze/v5/systems/{system_id}/notifications",
            json={"deviceId": device_id},
            retry=False,
        )

    async def is_registered(self, system_id: int) -> dict[str, Any]:
        return await self._transport.request_object(
            "GET", f"/topaze/v5/systems/{system_id}/notifications/registered"
        )

    async def unregister_all(self, system_id: int) -> None:
        """WARNING: removes every push registration of the installation."""
        await self._transport.request(
            "DELETE", f"/topaze/v5/systems/{system_id}/notifications/all", retry=False
        )

    async def list_receivers(self, system_id: int) -> list[dict[str, Any]]:
        """Who is alerted, by mail and by push, and for what."""
        data = await self._transport.request("GET", f"/topaze/v5/systems/{system_id}/notifications")
        return dicts(data)

    async def update_receiver(
        self, system_id: int, receiver_id: int, receiver: dict[str, Any]
    ) -> None:
        """`receiver` is one entry of `list_receivers`, changed."""
        await self._transport.request(
            "PUT",
            f"/topaze/v5/systems/{system_id}/notifications/{segment(receiver_id)}",
            json=receiver,
            retry=False,
        )

    async def add_contact(
        self, system_id: int, username: str, email: str, *, intrusion: bool, anomaly: bool
    ) -> None:
        """Add an alert contact, alerted by mail for intrusions and anomalies as chosen."""
        await self._transport.request(
            "POST",
            f"/topaze/v5/systems/{system_id}/contacts",
            json={
                "username": username,
                "email": email,
                "alertConfigurationMail": {
                    "notificationsMailIntrusion": intrusion,
                    "notificationsMailAnomaly": anomaly,
                },
            },
            retry=False,
        )

    async def update_contact(
        self, system_id: int, contact_id: int, username: str, email: str
    ) -> None:
        await self._transport.request(
            "PUT",
            f"/topaze/v5/systems/{system_id}/contacts/{segment(contact_id)}",
            json={"username": username, "email": email},
            retry=False,
        )

    async def delete_contact(self, system_id: int, contact_id: int) -> None:
        await self._transport.request(
            "DELETE", f"/topaze/v5/systems/{system_id}/contacts/{segment(contact_id)}", retry=False
        )
