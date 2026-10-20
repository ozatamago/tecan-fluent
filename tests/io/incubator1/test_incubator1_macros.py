"""Checks that the XML for Incubator1 matches the macros in GUI scripts 01-07. No device access."""

import pytest

from fakes import gui_macro, macro_obj
from unitelabs.tecan_fluent.io.fluentcontrol.errors import BackendError
from unitelabs.tecan_fluent.io.incubator1.macros import (
    incubator1_macro_xml,
    incubator1_set_temperature_xml,
    incubator1_start_shaker_xml,
)


@pytest.mark.parametrize(
    ("xml", "fixture"),
    [
        (incubator1_set_temperature_xml(37), "Incubator1_SetTemperature_1.xml"),  # 05: "0,37"
        (incubator1_set_temperature_xml(25), "Incubator1_SetTemperature_2.xml"),  # 05: "0,25"
        (incubator1_macro_xml("Incubator1_CloseDoor"), "Incubator1_CloseDoor_1.xml"),
        (incubator1_start_shaker_xml(5), "Incubator1_StartShaker_1.xml"),  # Sub_KineticMeasurement: "5"
        (incubator1_macro_xml("Incubator1_StopShaker"), "Incubator1_StopShaker_1.xml"),
    ],
)
def test_matches_gui_script_macro(xml, fixture):
    assert macro_obj(xml) == gui_macro(fixture)


def test_unlisted_moving_macros_are_refused():
    with pytest.raises(BackendError):
        incubator1_macro_xml("Incubator1_InsertPlate")
