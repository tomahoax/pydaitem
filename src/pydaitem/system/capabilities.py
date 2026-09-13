"""Arming capability discovery: `system.capabilities.*`.

Caches what the installation supports, since discovery needs a panel session and a full
widgets read. Guarded by a lock so two concurrent callers (e.g. two `arm()` calls racing to
discover presets) cannot interleave writes to the cache, the same shape as
`_Auth.ensure_token`'s own double-checked lock.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..const import ArmMode
from ..exceptions import DaitemError
from .state import _SystemState

_LOGGER = logging.getLogger(__name__)

#: Widget item names, in preference order, that identify the "presence" preset. The
#: installation exposes them through the widgets endpoint; matching on the name keeps the
#: preset index out of consumer code.
_PRESENCE_ITEM_NAMES = ("partial_arming_name_presence",)


class _Capabilities:
    def __init__(self, state: _SystemState) -> None:
        self._state = state
        self._arm_modes: frozenset[ArmMode] | None = None
        self._presets: dict[ArmMode, int] = {}
        self._lock = asyncio.Lock()

    @property
    def discovered(self) -> bool:
        """Whether the arming modes were read from the panel, not the AWAY fallback.

        False means discovery never ran or was blocked, so a consumer can tell a genuine
        away-only installation from a degraded one and act accordingly.
        """
        return self._arm_modes is not None

    def preset_for(self, mode: ArmMode) -> int | None:
        """The preset index resolved for `mode`, or None if not discovered (yet)."""
        return self._presets.get(mode)

    async def arm_modes(self) -> frozenset[ArmMode]:
        """Arming modes this installation actually supports.

        Discovered once from the widgets configuration, so a consumer advertises only what
        the panel offers instead of assuming a fixed set. `AWAY` is always available; the
        partial modes depend on the presets defined on the installation.
        """
        if self._arm_modes is not None:
            return self._arm_modes

        async with self._lock:
            # Re-check inside the lock: a concurrent caller may have just discovered.
            if self._arm_modes is not None:
                return self._arm_modes

            state = self._state
            modes = {ArmMode.AWAY}
            try:
                # The widgets endpoint needs an open panel session, unlike the inventory.
                async with state.client.panel.session(state.system_id, state.code):
                    items = await state.client.commands.list_presets(state.system_id)
            except DaitemError as err:
                # Best-effort: a failure must not prevent arming. Not cached either, so a
                # discovery blocked by another device is retried on the next call rather
                # than permanently downgrading the reported capabilities.
                _LOGGER.debug("Could not discover arming presets: %s", err)
                return frozenset(modes)

            for item in items:
                index = item.get("id")
                if not isinstance(index, int):
                    continue
                name = str(item.get("name") or "")
                if name in _PRESENCE_ITEM_NAMES and ArmMode.PRESENCE not in self._presets:
                    self._presets[ArmMode.PRESENCE] = index
                elif ArmMode.PARTIAL not in self._presets:
                    self._presets[ArmMode.PARTIAL] = index
                elif ArmMode.PARTIAL_2 not in self._presets:
                    self._presets[ArmMode.PARTIAL_2] = index

            modes.update(self._presets)
            self._arm_modes = frozenset(modes)
            return self._arm_modes

    async def list_presets(self) -> list[dict[str, Any]]:
        """Raw partial-arming presets defined on the installation (`id` and `name`).

        `arm_modes()` resolves these into the stable `ArmMode` vocabulary, which discards
        whatever name Daitem (or the installer, if the preset was renamed in the app)
        assigned beyond the "presence" special case. Use this to see the raw names, for
        instance to match an installation's own wording instead of a generic label.
        """
        state = self._state
        async with state.client.panel.session(state.system_id, state.code):
            return await state.client.commands.list_presets(state.system_id)
