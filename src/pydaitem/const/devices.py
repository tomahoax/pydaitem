"""Vocabulary of automations, cameras and clips, as the API sends it.

Models keep any other value as a plain string, so an unexpected one is visible instead of
dropped.

A member set to `auto()` is sent as its own name. An explicit value marks where the API's
spelling differs from the name, such as `ONDEMAND` or `UNKNOW`.
"""

from __future__ import annotations

from enum import StrEnum, auto
from typing import Any


class _AsNamed(StrEnum):
    """A `StrEnum` whose `auto()` value is the member's name, unchanged."""

    @staticmethod
    def _generate_next_value_(name: str, start: int, count: int, last_values: list[Any]) -> str:
        return name


class AutomatismCategory(_AsNamed):
    """What an automation drives. `UNKNOW` is the API's own spelling."""

    GARAGE = auto()
    GATE = auto()
    LIGHT = auto()
    PLUG = auto()
    SHUTTER = auto()
    UNKNOWN = "UNKNOW"


class AutomatismCommand(_AsNamed):
    """Commands an automation may accept, listed per automation in `available_commands`."""

    ON = auto()
    OFF = auto()
    TIMER = auto()
    SWITCH = auto()
    PULSE = auto()
    POSITION = auto()
    STEP_UP = auto()
    STEP_DOWN = auto()
    UP = auto()
    DOWN = auto()
    STOP = auto()


class AutomatismStateType(_AsNamed):
    """How an automation reports its state: on, off, or a position."""

    ON = auto()
    OFF = auto()
    POSITION = auto()


class CameraType(_AsNamed):
    DAHUA = auto()
    DAHUA_CLOUD = auto()
    DAITEM_CLOUD = auto()
    UNKNOWN = auto()


class ClipKind(_AsNamed):
    """Why a clip was recorded."""

    ALARM = auto()
    ON_DEMAND = "ONDEMAND"


class ClipCategory(_AsNamed):
    """Where a clip comes from. It is also the `deviceType` segment of the download path."""

    DETECTOR = auto()
    CAMERA = auto()
    ARCHIVE = auto()


class ClipFormat(_AsNamed):
    MPEG4 = auto()
    JPEG = auto()


class PanelMode(_AsNamed):
    """Panel modes for `client.panel.switch_mode`. Installer territory."""

    INSTALLATION = auto()
    TEST = auto()
    USAGE = "UTILISATION"


class InstallerAccess(_AsNamed):
    """Installer remote access levels."""

    FORBIDDEN = auto()
    TEST_ONLY = auto()
    WHEN_DISARMED = "USE_ON_SYSTEM_STOPPED"
    TOTAL = auto()


class PpmsAlert(_AsNamed):
    """Safety plan alerts (PPMS), for professional sites."""

    ATTACK = auto()
    NATURAL_HAZARD = auto()
