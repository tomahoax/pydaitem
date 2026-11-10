"""Installation and devices beyond the inventory: `client.devices.*`.

WARNING: `set_inhibited` changes what the alarm watches, and `update_firmware` flashes a
device remotely.
"""

from __future__ import annotations

from typing import Any

from .paths import segment
from .transport import _Transport


class _Devices:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def set_inhibited(self, system_id: int, serial_number: str, inhibited: bool) -> None:
        """Inhibit a device (the alarm ignores it) or restore it."""
        await self._transport.request(
            "PATCH",
            f"/topaze/v1/systems/{system_id}/products/{segment(serial_number)}",
            json={"isInhibited": inhibited},
            retry=False,
        )

    async def update_firmware(
        self, system_id: int, serial_number: str, firmware_file_name: str
    ) -> dict[str, Any]:
        """Start a firmware update. Answers `{status}`: PENDING, OK or KO."""
        return await self._transport.request_object(
            "POST",
            f"/topaze/v1/systems/{system_id}/updateFirmware",
            json={"firmwareFileName": firmware_file_name, "serialNumber": serial_number},
            retry=False,
        )

    async def rename(self, system_id: int, name: str) -> None:
        await self._transport.request(
            "PUT", f"/topaze/v5/systems/{system_id}/name", json={"name": name}, retry=False
        )

    async def set_gprs_phone(self, system_id: int, phone_number: str) -> None:
        await self._transport.request(
            "PUT",
            f"/topaze/v5/systems/{system_id}/gprs-phone-number",
            json={"phoneNumber": phone_number},
            retry=False,
        )

    async def countries(self) -> dict[str, Any]:
        """Countries the app offers. Needs no installation."""
        return await self._transport.request_object("GET", "/topaze/v5/configuration")

    async def get_configuration(self, system_id: int, role: int | None = None) -> dict[str, Any]:
        """Installation record by role, which carries the `transmitterId` among others."""
        payload: dict[str, Any] = {"systemId": system_id}
        if role is not None:
            payload["role"] = role
        return await self._transport.request_object(
            "POST", "/topaze/configuration/getConfiguration", json=payload
        )
