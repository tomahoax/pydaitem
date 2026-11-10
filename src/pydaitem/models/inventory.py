"""Device inventory: `Anomalies`, `Firmware`, `Device`, `Inventory`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..const import RAW_TO_FAULT, DeviceKind, Fault
from ._shared import _warn_unknown, dicts


@dataclass(slots=True, kw_only=True)
class Anomalies:
    """Faults reported by a device. Keys vary with the device type."""

    flags: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Anomalies:
        anomalies = cls(
            flags={str(k): bool(v) for k, v in data.items()} if isinstance(data, dict) else {}
        )
        # Warn now, once per key: a fault key the API renamed would otherwise just vanish.
        anomalies.unknown_keys  # noqa: B018 - read for its warning
        return anomalies

    @property
    def faults(self) -> set[Fault]:
        """Active faults, as semantic values. Use this, not `flags`."""
        return {
            fault
            for key, raised in self.flags.items()
            if raised and (fault := RAW_TO_FAULT.get(key)) is not None
        }

    def has(self, fault: Fault) -> bool | None:
        """Whether a fault is raised, or None when this device does not report it."""
        for key, raised in self.flags.items():
            if RAW_TO_FAULT.get(key) is fault:
                return raised
        return None

    @property
    def unknown_keys(self) -> set[str]:
        """Raw keys this library does not map yet. Never fatal, warned once each."""
        unknown = {key for key in self.flags if key not in RAW_TO_FAULT}
        for key in unknown:
            _warn_unknown("anomaly key", key)
        return unknown

    @property
    def active(self) -> list[str]:
        """Raw keys of the raised flags. Diagnostic only, not part of the contract."""
        return [k for k, v in self.flags.items() if v]

    def __bool__(self) -> bool:
        return any(self.flags.values())


@dataclass(slots=True, kw_only=True)
class Firmware:
    """One firmware image reported by the panel or by its transmission module.

    `kind` is the raw `firmwareType`, kept as a string rather than an enum: `SOFT` and
    `RADIO` are the known values, and an unrecognised one must not be dropped.
    """

    kind: str
    version: str
    release_date: int | None = None
    file_name: str = ""
    is_critical: bool = False
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Firmware:
        current = data.get("currentVersion")
        current = current if isinstance(current, dict) else {}
        return cls(
            kind=data.get("firmwareType") or "",
            version=str(current.get("releaseVersion") or ""),
            release_date=current.get("releaseDate"),
            file_name=current.get("fileName") or "",
            is_critical=bool(current.get("isCritical")),
            raw=data,
        )


def _firmwares(container: dict[str, Any]) -> list[Firmware]:
    return [Firmware.from_json(f) for f in dicts(container.get("firmwareInfo"), "firmwares")]


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _version(firmwares: list[Firmware], kind: str) -> str | None:
    return next((f.version for f in firmwares if f.kind == kind and f.version), None)


@dataclass(slots=True, kw_only=True)
class Device:
    """One device of the inventory: a detector, a control, a siren, the box...

    Every family shares this shape in the app's models.
    """

    index: int
    name: str
    serial_number: str
    type: str
    kind: DeviceKind
    """The inventory section it comes from."""
    group: int | None = None
    inhibited: bool = False
    inhibitable: bool = False
    is_video: bool = False
    anomalies: Anomalies = field(default_factory=Anomalies)
    firmwares: list[Firmware] = field(default_factory=list)
    """Empty for most devices: no detector reported one on the installations read."""
    triggered: bool | None = None
    """Whether a fire or PPMS trigger has gone off. None for the other families."""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any], kind: DeviceKind) -> Device:
        triggered = data.get("isTriggered")
        return cls(
            index=data.get("index", 0),
            name=data.get("name") or "",
            serial_number=data.get("serialNumber") or "",
            type=data.get("type") or "",
            kind=kind,
            group=data.get("group"),
            inhibited=bool(data.get("isInhibited")),
            inhibitable=bool(data.get("isInhibitable")),
            is_video=bool(data.get("isVideo")),
            anomalies=Anomalies.from_json(data.get("anomalies")),
            firmwares=_firmwares(data),
            triggered=triggered if isinstance(triggered, bool) else None,
            raw=data,
        )


def _devices(data: dict[str, Any]) -> list[Device]:
    """Every device of the inventory, section by section, as the app's device screen."""
    generic = data.get("genericSensors")
    generic = generic if isinstance(generic, dict) else {}
    sections = [
        (DeviceKind.SENSOR, dicts(generic, "sensors")),
        (DeviceKind.COMMAND, dicts(data.get("commands"))),
        (DeviceKind.SIREN, dicts(data.get("sirens"))),
        (DeviceKind.TRANSMITTER, dicts(data.get("transmitters"))),
        (DeviceKind.TRANSCEIVER, dicts(data.get("transceivers"))),
        (DeviceKind.BOX, dicts([data.get("box")])),
        (DeviceKind.FIRE_TRIGGER, dicts(generic, "fireTriggers")),
        (DeviceKind.PPMS_TRIGGER, dicts(generic, "ppmsTriggers")),
    ]
    return [Device.from_json(entry, kind) for kind, entries in sections for entry in entries]


@dataclass(slots=True, kw_only=True)
class Inventory:
    """Device inventory, from `/v2/systems/<id>/configuration`.

    Note: the API does **not** expose live open/closed detector state. Only identity,
    group, inhibition and faults are available.
    """

    central_serial: str = ""
    central_type: str = ""
    has_io: bool = False
    central_anomalies: Anomalies = field(default_factory=Anomalies)
    plug_serial: str = ""
    central_firmwares: list[Firmware] = field(default_factory=list)
    plug_firmwares: list[Firmware] = field(default_factory=list)
    devices: list[Device] = field(default_factory=list)
    alerts_enabled: bool | None = None
    """Whether alerts can be set up on this installation (`isAlertEnabled`)."""
    scenarios_enabled: bool | None = None
    """Whether scenarios can be set up on this installation (`isScenarioEnabled`)."""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Inventory:
        central = _object(data.get("central"))
        plug = _object(central.get("plug")) or _object(data.get("plug"))
        alerts, scenarios = data.get("isAlertEnabled"), data.get("isScenarioEnabled")
        return cls(
            central_serial=central.get("serialNumber") or "",
            central_type=central.get("type") or "",
            has_io=bool(central.get("hasIO")),
            central_anomalies=Anomalies.from_json(central.get("anomalies")),
            plug_serial=plug.get("serialNumber") or "",
            central_firmwares=_firmwares(central),
            plug_firmwares=_firmwares(plug),
            devices=_devices(data),
            alerts_enabled=alerts if isinstance(alerts, bool) else None,
            scenarios_enabled=scenarios if isinstance(scenarios, bool) else None,
            raw=data,
        )

    @property
    def sensors(self) -> list[Device]:
        return self.of_kind(DeviceKind.SENSOR)

    @property
    def controls(self) -> list[Device]:
        return self.of_kind(DeviceKind.COMMAND)

    def of_kind(self, kind: DeviceKind) -> list[Device]:
        """The devices of one family, such as `of_kind(DeviceKind.SIREN)`."""
        return [d for d in self.devices if d.kind == kind]

    @property
    def software_version(self) -> str | None:
        """Main panel software, `SOFT` on the central unit."""
        return _version(self.central_firmwares, "SOFT")

    @property
    def radio_version(self) -> str | None:
        """Panel radio firmware, versioned separately from the software."""
        return _version(self.central_firmwares, "RADIO")

    @property
    def transmitter_version(self) -> str | None:
        """Transmission module software, carried by the panel's `plug`."""
        return _version(self.plug_firmwares, "SOFT")
