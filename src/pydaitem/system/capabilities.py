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

from ..const import PRESET_ITEM_NAMES, ArmMode
from ..exceptions import DaitemError
from .state import _SystemState, bounded

_LOGGER = logging.getLogger(__name__)

#: Modes left to an item whose name is not one of the above, in order.
_FALLBACK_MODES = (ArmMode.PARTIAL, ArmMode.PARTIAL_2)


class _Capabilities:
    def __init__(self, state: _SystemState) -> None:
        self._state = state
        self._arm_modes: frozenset[ArmMode] | None = None
        self._presets: dict[ArmMode, int] = {}
        self._items: list[dict[str, Any]] | None = None
        self._lock = asyncio.Lock()
        # A discovery was asked for and blocked: the next session a read opens makes it.
        self._wanted = False

    @property
    def discovered(self) -> bool:
        """Whether the arming modes were read from the panel, not the AWAY fallback.

        False means discovery never ran or was blocked, so a consumer can tell a genuine
        away-only installation from a degraded one and act accordingly.
        """
        return self._arm_modes is not None

    def _preset_for(self, mode: ArmMode) -> int | None:
        """The preset index resolved for `mode`, or None if not discovered (yet)."""
        return self._presets.get(mode)

    async def arm_modes(self) -> frozenset[ArmMode]:
        """Arming modes this installation actually supports.

        Discovered once from the widgets configuration, so a consumer advertises only what
        the panel offers instead of assuming a fixed set. `AWAY` is always available; the
        partial modes depend on the presets defined on the installation.

        Never raises a `DaitemError`. A discovery that fails (panel busy, network) returns
        `{AWAY}`, leaves `discovered` False and is tried again on the next call.
        """
        if self._arm_modes is not None:
            return self._arm_modes

        async with self._lock:
            # Re-check inside the lock: a concurrent caller may have just discovered.
            if self._arm_modes is not None:
                return self._arm_modes

            try:
                # The widgets endpoint needs an open panel session, unlike the inventory.
                async with self._state.deadline("capabilities.arm_modes"), self._state.session():
                    await self._discover()
            except DaitemError as err:
                # Best-effort: a failure must not prevent arming. Not cached either, so a
                # discovery blocked by another device is retried on the next call rather
                # than permanently downgrading the reported capabilities. Until then, the
                # next session a read opens makes it, rather than a session of its own.
                _LOGGER.debug("Could not discover arming presets: %s", err)
                self._wanted = True
                return frozenset({ArmMode.AWAY})
            assert self._arm_modes is not None
            return self._arm_modes

    async def _discover(self) -> None:
        """Read the presets inside the session the caller holds, and keep them.

        Takes no lock of its own: a command calls it while holding the panel, and the two
        locks must never be taken in opposite orders.
        """
        state = self._state
        items = await state.client.commands.list_presets(state.system_id)
        self._items = items
        self._presets = _resolve_presets(items)
        self._arm_modes = frozenset({ArmMode.AWAY, *self._presets})
        self._wanted = False

    async def _discover_if_wanted(self) -> None:
        """Make a blocked discovery in a session a read already opened. Never raises."""
        if not self._wanted or self._arm_modes is not None:
            return
        try:
            await self._discover()
        except DaitemError as err:
            _LOGGER.debug("Could not discover arming presets: %s", err)

    @bounded("capabilities.presets")
    async def presets(self) -> list[dict[str, Any]]:
        """Raw partial-arming presets defined on the installation (`id` and `name`).

        `arm_modes()` resolves these into the stable `ArmMode` vocabulary through the app's
        own item names (`partial_arming_name_presence`, `_1`, `_2`), which discards any
        label the installer gave the preset. Use this to see the raw names, for
        instance to match an installation's own wording instead of a generic label.
        Read once, with the arming modes: a later call costs no request. The first call may
        hold a panel session, so may raise the session errors, unlike `arm_modes()`.
        """
        if self._items is None:
            async with self._state.session():
                await self._discover()
        assert self._items is not None
        return [dict(item) for item in self._items]


def _resolve_presets(items: list[dict[str, Any]]) -> dict[ArmMode, int]:
    """Preset index for each mode: by the app's item names first, then by order.

    The order fallback covers names the app does not use, so an installation never loses a
    preset it has, even if it then lands on a mode by position rather than by name.
    """
    presets: dict[ArmMode, int] = {}
    unnamed: list[int] = []
    for item in items:
        index = item.get("id")
        if not isinstance(index, int):
            continue
        mode = PRESET_ITEM_NAMES.get(str(item.get("name") or ""))
        if mode is not None and mode not in presets:
            presets[mode] = index
        else:
            unnamed.append(index)
    free = [mode for mode in _FALLBACK_MODES if mode not in presets]
    for mode, index in zip(free, unnamed, strict=False):
        presets[mode] = index
    return presets
