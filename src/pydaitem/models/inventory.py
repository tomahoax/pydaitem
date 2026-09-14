"""Device inventory: `Anomalies`, `Firmware`, `Device`, `Inventory`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..const import RAW_TO_FAULT, Fault
from ._shared import _warn_unknown


@dataclass(slots=True)
class Anomalies:
    """Faults reported by a device. Keys vary with the device type."""

    flags: dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> Anomalies:
        return cls(flags={k: bool(v) for k, v in (data or {}).items()})

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


@dataclass(slots=True)
class Firmware:
    """One firmware image reported by the panel or by its transmission module.

    `kind` is the raw `firmwareType`, kept as a string rather than an enum: `SOFT` and
    `RADIO` are the two values observed, and an unrecognised one must not be dropped.
    """

    kind: str
    version: str
    release_date: int | None = None
    file_name: str = ""
    is_critical: bool = False

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Firmware:
        current = data.get("currentVersion") or {}
        return cls(
            kind=data.get("firmwareType") or "",
            version=str(current.get("releaseVersion") or ""),
            release_date=current.get("releaseDate"),
            file_name=current.get("fileName") or "",
            is_critical=bool(current.get("isCritical")),
        )


def _firmwares(container: dict[str, Any]) -> list[Firmware]:
    entries = (container.get("firmwareInfo") or {}).get("firmwares") or []
    return [Firmware.from_json(f) for f in entries]


def _version(firmwares: list[Firmware], kind: str) -> str | None:
    return next((f.version for f in firmwares if f.kind == kind and f.version), None)


@dataclass(slots=True)
class Device:
    """A detector (`sensor`) or a control device (`command`)."""

    index: int
    name: str
    serial_number: str
    type: str
    kind: str
    """Either "sensor" or "command", from the originating configuration section."""
    group: int | None = None
    inhibited: bool = False
    inhibitable: bool = False
    is_video: bool = False
    anomalies: Anomalies = field(default_factory=Anomalies)

    @classmethod
    def from_json(cls, data: dict[str, Any], kind: str) -> Device:
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
        )


@dataclass(slots=True)
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
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Inventory:
        central = data.get("central") or {}
        plug = central.get("plug") or data.get("plug") or {}
        sensors = (data.get("genericSensors") or {}).get("sensors") or []
        commands = data.get("commands") or []
        return cls(
            central_serial=central.get("serialNumber") or "",
            central_type=central.get("type") or "",
            has_io=bool(central.get("hasIO")),
            central_anomalies=Anomalies.from_json(central.get("anomalies")),
            plug_serial=plug.get("serialNumber") or "",
            central_firmwares=_firmwares(central),
            plug_firmwares=_firmwares(plug),
            devices=[Device.from_json(d, "sensor") for d in sensors]
            + [Device.from_json(d, "command") for d in commands],
            raw=data,
        )

    @property
    def sensors(self) -> list[Device]:
        return [d for d in self.devices if d.kind == "sensor"]

    @property
    def controls(self) -> list[Device]:
        return [d for d in self.devices if d.kind == "command"]

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
