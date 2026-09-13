"""Tests of the semantic layer that decouples consumers from the raw API.

These guard the promise that a change in the Daitem API is absorbed here rather than by
downstream code: an unknown value must degrade visibly, never silently.
"""

from __future__ import annotations

import logging

from pydaitem import Fault, PanelState, SystemStatus
from pydaitem.const import ARMED_PANEL_STATES
from pydaitem.models import Anomalies, _warn_unknown


def test_armed_partial_2_counts_as_armed_even_though_unmapped() -> None:
    """`ArmMode.PARTIAL_2`'s own armed state has no raw mapping yet (never observed live),
    but the semantic value itself must already count as armed once one is added."""
    assert PanelState.ARMED_PARTIAL_2 in ARMED_PANEL_STATES


def test_known_states_map_to_semantic_values() -> None:
    cases = {
        "off": PanelState.DISARMED,
        "tempo": PanelState.ARMING,
        "tempo1": PanelState.ARMING,
        "tempogroup": PanelState.ARMING,
        "on": PanelState.ARMED_FULL,
        "presence": PanelState.ARMED_PRESENCE,
        "group": PanelState.ARMED_GROUPS,
        "partial1": PanelState.ARMED_PARTIAL,
    }
    for raw, expected in cases.items():
        assert SystemStatus.from_json({"systemState": raw}).panel_state is expected


def test_unknown_state_degrades_to_unknown_and_warns(caplog) -> None:
    """A state the library does not know must be visible, not silently absent.

    This matters concretely: the triggered-alarm state has never been captured, so it will
    first reach us as an unknown value.
    """
    _warn_unknown.cache_clear()
    status = SystemStatus.from_json({"systemState": "someNewStateFromAnAppUpdate"})

    with caplog.at_level(logging.WARNING, logger="pydaitem.models"):
        assert status.panel_state is PanelState.UNKNOWN

    assert "someNewStateFromAnAppUpdate" in caplog.text
    # The raw value stays available for diagnostics.
    assert status.state == "someNewStateFromAnAppUpdate"


def test_unknown_state_warns_only_once(caplog) -> None:
    _warn_unknown.cache_clear()
    status = SystemStatus.from_json({"systemState": "repeatedUnknown"})
    with caplog.at_level(logging.WARNING, logger="pydaitem.models"):
        for _ in range(5):
            assert status.panel_state is PanelState.UNKNOWN
    assert caplog.text.count("repeatedUnknown") == 1


def test_armed_and_arming_use_semantic_states() -> None:
    arming = SystemStatus.from_json({"systemState": "tempogroup"})
    assert arming.is_arming and not arming.is_armed

    armed = SystemStatus.from_json({"systemState": "presence"})
    assert armed.is_armed and not armed.is_arming

    unknown = SystemStatus.from_json({"systemState": "???"})
    assert not unknown.is_armed and not unknown.is_arming


def test_anomalies_expose_semantic_faults() -> None:
    anomalies = Anomalies.from_json(
        {
            "mainPowerSupplyAlert": False,
            "defaultMediaAlert": True,
            "autoprotectionMechanicalAlert": True,
        }
    )
    assert anomalies.faults == {Fault.TRANSMISSION_MEDIA, Fault.TAMPER_MECHANICAL}
    assert anomalies.has(Fault.MAIN_POWER) is False
    assert anomalies.has(Fault.TRANSMISSION_MEDIA) is True
    # A fault this device does not report is unknown, not "not raised".
    assert anomalies.has(Fault.MASKING) is None


def test_detector_faults_are_mapped() -> None:
    anomalies = Anomalies.from_json({"powerSupplyAlert": True, "radioAlert": True})
    assert anomalies.faults == {Fault.BATTERY, Fault.RADIO}


def test_unknown_anomaly_key_is_reported_not_fatal(caplog) -> None:
    _warn_unknown.cache_clear()
    anomalies = Anomalies.from_json({"brandNewAlert": True, "radioAlert": True})

    # A key we cannot map must never break the known ones.
    assert anomalies.faults == {Fault.RADIO}
    with caplog.at_level(logging.WARNING, logger="pydaitem.models"):
        assert anomalies.unknown_keys == {"brandNewAlert"}
    assert "brandNewAlert" in caplog.text


def test_connect_response_group_shape_is_normalised() -> None:
    """The connect response encodes groups differently from /state.

    Regression: `connect` puts active group ids in `groups` as bare integers, with the
    objects in `groupList`. Parsing it like a /state payload crashed as soon as a group
    was active, which only showed up when issuing a command on an armed system.
    """
    status = SystemStatus.from_json(
        {
            "systemState": "on",
            "groups": [1, 2],
            "groupList": [
                {"id": 1, "name": None, "active": False},
                {"id": 2, "name": None, "active": False},
                {"id": 3, "name": None, "active": False},
            ],
        }
    )
    # The ids listed in `groups` are the active ones, whatever groupList says.
    assert status.active_groups == [1, 2]
    assert len(status.groups) == 3


def test_connect_response_without_group_catalogue() -> None:
    status = SystemStatus.from_json({"systemState": "group", "groups": [2]})
    assert status.active_groups == [2]


def test_state_response_group_shape_still_works() -> None:
    status = SystemStatus.from_json(
        {"systemState": "on", "groups": [{"id": 1, "active": True}, {"id": 2, "active": False}]}
    )
    assert status.active_groups == [1]
