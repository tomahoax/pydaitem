"""Raw API vocabulary, the library's own semantic vocabulary, and the mapping between them.

The 13 raw states and the exit delay list are in docs/api/entities.md.

A member set to `auto()` takes its name in lower case, `StrEnum`'s own rule. An explicit
value marks where the raw value differs from that.
"""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Final


class SystemState(StrEnum):
    """Raw `systemState` values, as sent by the API, in the app's declaration order.

    **Not part of the public contract.** Consumers should use `PanelState`, which is
    stable and owned by this library. These raw values exist only so the mapping below has
    something to name.
    """

    OFF = auto()
    """Disarmed."""
    TEMPO = auto()
    """Exit delay running, full arming in progress."""
    TEMPOGROUP = auto()
    """Exit delay running for one or more groups."""
    TEMPO1 = auto()
    """Exit delay running for the first named preset (`ArmMode.PARTIAL`)."""
    TEMPO2 = auto()
    """Exit delay running for the second named preset (`ArmMode.PARTIAL_2`)."""
    ON = auto()
    """Fully armed."""
    GROUP = auto()
    """One or more groups armed."""
    PARTIAL1 = auto()
    """Armed through the first named preset (`ArmMode.PARTIAL`)."""
    PARTIAL2 = auto()
    """Armed through the second named preset (`ArmMode.PARTIAL_2`)."""
    PRESENCE = auto()
    """Partially armed through the "presence" preset."""
    APPRENT = auto()
    """Installation (learning) mode, set up by the installer."""
    ESSAI = auto()
    """Test mode."""
    EMPTY = ""
    """No state given. The app treats it as a case of its own, `unknown`."""


class PanelState(StrEnum):
    """Semantic panel state. **Stable public contract.**

    Consumers map from these values, never from the raw API strings. When the API gains or
    renames a state, only `RAW_TO_PANEL_STATE` below changes; nothing downstream does.
    """

    DISARMED = auto()
    ARMING = auto()
    """An exit delay is running; the state will settle on its own."""
    ARMED_FULL = auto()
    ARMED_PRESENCE = auto()
    """Partially armed through the "presence" preset."""
    ARMED_PARTIAL = auto()
    """Partially armed through the first named preset (`ArmMode.PARTIAL`)."""
    ARMED_PARTIAL_2 = auto()
    """Partially armed through the second named preset (`ArmMode.PARTIAL_2`), distinct from
    `ARMED_PARTIAL` (`partial2`)."""
    ARMED_GROUPS = auto()
    """Partially armed by direct group activation."""
    TRIGGERED = auto()
    """Alarm going off. No raw value maps to it yet."""
    MAINTENANCE = auto()
    """Installation or test mode: the panel is being worked on and cannot be driven as usual.
    The raw value (`SystemStatus.state`) tells which."""
    UNKNOWN = auto()
    """The API returned no state, or one this library does not know about yet."""


#: Raw API value -> semantic state. The single place to edit when the API changes.
#:
#: Every raw value the app knows has an entry. The states mapped to ARMING are exactly the
#: app's own exit delay list. No entry maps to TRIGGERED yet: the app has no raw value for a
#: sounding alarm, so it is still unknown. It will surface as UNKNOWN with a warning, which is
#: the point of the fallback. The empty value maps to UNKNOWN without a warning, as in the app.
RAW_TO_PANEL_STATE: Final[dict[str, PanelState]] = {
    SystemState.OFF: PanelState.DISARMED,
    SystemState.TEMPO: PanelState.ARMING,
    SystemState.TEMPOGROUP: PanelState.ARMING,
    SystemState.TEMPO1: PanelState.ARMING,
    SystemState.TEMPO2: PanelState.ARMING,
    SystemState.ON: PanelState.ARMED_FULL,
    SystemState.GROUP: PanelState.ARMED_GROUPS,
    SystemState.PARTIAL1: PanelState.ARMED_PARTIAL,
    SystemState.PARTIAL2: PanelState.ARMED_PARTIAL_2,
    SystemState.PRESENCE: PanelState.ARMED_PRESENCE,
    SystemState.APPRENT: PanelState.MAINTENANCE,
    SystemState.ESSAI: PanelState.MAINTENANCE,
    SystemState.EMPTY: PanelState.UNKNOWN,
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

    AWAY = auto()
    """Arm every group."""
    PRESENCE = auto()
    """Named partial preset, typically "someone is home"."""
    PARTIAL = auto()
    """A secondary partial preset, when the installation defines one."""
    PARTIAL_2 = auto()
    """A third partial preset, when the installation defines one, distinct from `PARTIAL`."""


class Fault(StrEnum):
    """Semantic device fault. **Stable public contract.**

    Consumers iterate over these, never over raw API keys.
    """

    MAIN_POWER = auto()
    BACKUP_POWER = auto()
    TRANSMISSION_MEDIA = auto()
    TAMPER_MECHANICAL = auto()
    TAMPER_WIRED = auto()
    BATTERY = auto()
    RADIO = auto()
    MASKING = auto()
    SENSOR = auto()
    LOOP = auto()


class DeviceKind(StrEnum):
    """Which section of the inventory a device comes from. **Stable public contract.**

    The app's device screen has one section per family. Fire and PPMS triggers are
    widgets in the app, listed here as devices since they report faults the same way.
    """

    SENSOR = auto()
    COMMAND = auto()
    SIREN = auto()
    TRANSMITTER = auto()
    TRANSCEIVER = auto()
    BOX = auto()
    FIRE_TRIGGER = auto()
    PPMS_TRIGGER = auto()


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


#: Widget item names of the presets the app knows, and the mode each one stands for. The
#: installation exposes them through the widgets endpoint. Matching on the name keeps the
#: preset index out of consumer code, and keeps the order of the items irrelevant. They are
#: the app's vocabulary, not a name someone chose, so redaction leaves them readable.
PRESET_ITEM_NAMES: Final[dict[str, ArmMode]] = {
    "partial_arming_name_presence": ArmMode.PRESENCE,
    "partial_arming_name_1": ArmMode.PARTIAL,
    "partial_arming_name_2": ArmMode.PARTIAL_2,
}
