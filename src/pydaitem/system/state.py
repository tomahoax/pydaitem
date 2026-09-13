"""Shared, immutable state: the client, the installation id and the alarm code."""

from __future__ import annotations

from ..client import DaitemClient


class _SystemState:
    def __init__(self, client: DaitemClient, system_id: int, code: str) -> None:
        """`code` is the alarm code of the account in use, not necessarily the master."""
        self.client = client
        self.system_id = system_id
        self.code = code
