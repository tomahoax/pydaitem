"""Raw API vocabulary, the library's own semantic vocabulary, and the mapping between them.

Reverse-engineered from the iOS Daitem Secure 6.0.2 app traffic.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class SystemState(StrEnum):
    """Raw `systemState` values, as sent by the API.

    **Not part of the public contract.** Consumers should use `PanelState`, which is
    stable and owned by this library. These raw values exist only so the mapping below has
    something to name.
    """

    OFF = "off"
    """Disarmed."""
    TEMPO = "tempo"
    """Exit delay running, full arming in progress."""
    TEMPO1 = "tempo1"
    """Exit delay running for a named partial preset (observed for `ArmMode.PARTIAL`)."""
    ON = "on"
    """Fully armed."""
    PRESENCE = "presence"
    """Partially armed through the "presence" preset."""
    TEMPOGROUP = "tempogroup"
    """Exit delay running for one or more groups."""
    GROUP = "group"
    """One or more groups armed."""
    PARTIAL1 = "partial1"
    """Armed through a named partial preset other than "presence" (`ArmMode.PARTIAL`)."""


class PanelState(StrEnum):
    """Semantic panel state. **Stable public contract.**

    Consumers map from these values, never from the raw API strings. When the API gains or
    renames a state, only `RAW_TO_PANEL_STATE` below changes; nothing downstream does.
    """

    DISARMED = "disarmed"
    ARMING = "arming"
    """An exit delay is running; the state will settle on its own."""
    ARMED_FULL = "armed_full"
    ARMED_PRESENCE = "armed_presence"
    """Partially armed through the "presence" preset."""
    ARMED_PARTIAL = "armed_partial"
    """Partially armed through a secondary named preset (`ArmMode.PARTIAL`)."""
    ARMED_PARTIAL_2 = "armed_partial_2"
    """A third named preset's own armed state (`ArmMode.PARTIAL_2`), distinct from
    `ARMED_PARTIAL`. Not yet mapped from any raw value: add the entry to
    `RAW_TO_PANEL_STATE` once observed live."""
    ARMED_GROUPS = "armed_groups"
    """Partially armed by direct group activation."""
    TRIGGERED = "triggered"
    """Alarm going off. Never captured, so the raw value is still unknown."""
    UNKNOWN = "unknown"
    """The API returned a state this library does not know about yet."""


#: Raw API value -> semantic state. The single place to edit when the API changes.
#:
#: No entry maps to TRIGGERED yet: a triggered alarm was never captured, so its raw value
#: is unknown. It will surface as UNKNOWN with a warning, which is the point of the
#: fallback.
RAW_TO_PANEL_STATE: Final[dict[str, PanelState]] = {
    SystemState.OFF: PanelState.DISARMED,
    SystemState.TEMPO: PanelState.ARMING,
    SystemState.TEMPO1: PanelState.ARMING,
    SystemState.TEMPOGROUP: PanelState.ARMING,
    SystemState.ON: PanelState.ARMED_FULL,
    SystemState.PRESENCE: PanelState.ARMED_PRESENCE,
    SystemState.GROUP: PanelState.ARMED_GROUPS,
    SystemState.PARTIAL1: PanelState.ARMED_PARTIAL,
}

#: Semantic states that count as armed, fully or partially.
ARMED_PANEL_STATES: Final = frozenset(
    {
        PanelState.ARMED_FULL,
        PanelState.ARMED_PRESENCE,
        PanelState.ARMED_PARTIAL,
        PanelState.ARMED_PARTIAL_2,
        PanelState.ARMED_GROUPS,
    }
)


class ArmMode(StrEnum):
    """Arming modes an installation may support. **Stable public contract.**"""

    AWAY = "away"
    """Arm every group."""
    PRESENCE = "presence"
    """Named partial preset, typically "someone is home"."""
    PARTIAL = "partial"
    """A secondary partial preset, when the installation defines one."""
    PARTIAL_2 = "partial_2"
    """A third partial preset, when the installation defines one, distinct from `PARTIAL`."""


class Fault(StrEnum):
    """Semantic device fault. **Stable public contract.**

    Consumers iterate over these, never over raw API keys.
    """

    MAIN_POWER = "main_power"
    BACKUP_POWER = "backup_power"
    TRANSMISSION_MEDIA = "transmission_media"
    TAMPER_MECHANICAL = "tamper_mechanical"
    TAMPER_WIRED = "tamper_wired"
    BATTERY = "battery"
    RADIO = "radio"
    MASKING = "masking"
    SENSOR = "sensor"
    LOOP = "loop"


#: Raw anomaly key -> semantic fault. The single place to edit when the API changes.
#: Keys are shared between panels and detectors, hence one flat mapping.
RAW_TO_FAULT: Final[dict[str, Fault]] = {
    "mainPowerSupplyAlert": Fault.MAIN_POWER,
    "secondaryPowerSupplyAlert": Fault.BACKUP_POWER,
    "powerSupplyAlert": Fault.BATTERY,
    "defaultMediaAlert": Fault.TRANSMISSION_MEDIA,
    "autoprotectionMechanicalAlert": Fault.TAMPER_MECHANICAL,
    "autoprotectionWiredAlert": Fault.TAMPER_WIRED,
    "radioAlert": Fault.RADIO,
    "maskAlert": Fault.MASKING,
    "sensorAlert": Fault.SENSOR,
    "loopAlert": Fault.LOOP,
}
