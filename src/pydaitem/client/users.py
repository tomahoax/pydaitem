"""Users, access codes, rights and the installer: `client.users.*`.

WARNING: everything here but the reads changes who can operate the alarm. Owner accounts
only.
"""

from __future__ import annotations

from typing import Any

from .paths import segment
from .transport import _Transport


class _Users:
    def __init__(self, transport: _Transport) -> None:
        self._transport = transport

    async def list(self, system_id: int) -> dict[str, Any]:
        """Owner, restricted users, installer and service codes."""
        return await self._transport.request_object("GET", f"/topaze/v5/systems/{system_id}/users")

    async def get_code(self, system_id: int, code_id: int) -> dict[str, Any]:
        return await self._transport.request_object(
            "GET", f"/topaze/v5/systems/{system_id}/code/{segment(code_id)}"
        )

    async def installer_access(self, system_id: int) -> Any:
        """Current installer remote access level, as sent."""
        return await self._transport.request(
            "GET", f"/topaze/v5/systems/{system_id}/installer/access"
        )

    async def set_installer_access(self, system_id: int, access: str) -> None:
        """`access` is an `InstallerAccess` value."""
        await self._transport.request(
            "PUT", f"/topaze/v5/systems/{system_id}/installer/access/{segment(access)}", retry=False
        )

    async def change_installer(self, system_id: int, email: str) -> None:
        await self._transport.request(
            "PUT", f"/topaze/v1/systems/{system_id}/installer", json={"email": email}, retry=False
        )

    async def create_restricted(self, system_id: int, user: dict[str, Any]) -> None:
        """`user` is `{firstName, lastName, email, code, serviceCodeIndex, rights}`."""
        await self._transport.request(
            "POST", f"/topaze/v1/systems/{system_id}/users/restricted", json=user, retry=False
        )

    async def update_owner(self, system_id: int, owner: dict[str, Any]) -> None:
        """`owner` is `{firstName, lastName, country, address, zipCode, city, phone}`."""
        await self._transport.request(
            "PUT", f"/topaze/v1/systems/{system_id}/owner", json=owner, retry=False
        )

    async def update_restricted(self, system_id: int, first_name: str, last_name: str) -> None:
        await self._transport.request(
            "PUT",
            f"/topaze/v1/systems/{system_id}/restricted",
            json={"firstName": first_name, "lastName": last_name},
            retry=False,
        )

    async def set_email(self, system_id: int, user_id: int, email: str) -> None:
        await self._transport.request(
            "PUT",
            f"/topaze/v1/systems/{system_id}/users/{segment(user_id)}/email",
            json={"email": email},
            retry=False,
        )

    async def delete(self, system_id: int, user_id: int) -> None:
        await self._transport.request(
            "DELETE", f"/topaze/v1/systems/{system_id}/users/{segment(user_id)}", retry=False
        )

    async def set_code(self, system_id: int, user_id: int, code: str) -> None:
        """Change a user's alarm code."""
        await self._transport.request(
            "PUT",
            f"/topaze/v6/systems/{system_id}/users/{segment(user_id)}/accessCodes",
            json={"code": code},
            retry=False,
        )

    async def set_rights(self, system_id: int, user_id: int, rights: dict[str, Any]) -> None:
        """`rights` is `{alarms, automatism, lights, receivers, scenarios, videos}`."""
        await self._transport.request(
            "PUT",
            f"/topaze/v6/systems/{system_id}/users/{segment(user_id)}/rights",
            json=rights,
            retry=False,
        )
