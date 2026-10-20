"""Checks that the XML for the CPLC positions (inhecoMTC) matches the macros in GUI scripts 01-07. No device access."""

import pytest

from fakes import gui_macro, macro_obj
from unitelabs.tecan_fluent.io.cplc.macros import mtc_set_temperature_xml


@pytest.mark.parametrize(
    ("xml", "fixture"),
    [
        (mtc_set_temperature_xml(1, True, 4), "inhecoMTC_SetTemperature_3.xml"),  # 03: "1,True,4.0,0"
        (mtc_set_temperature_xml(3, True, 65), "inhecoMTC_SetTemperature_1.xml"),  # 06: "3,True,65.0,0"
        (mtc_set_temperature_xml(1, False, 37.5), "inhecoMTC_SetTemperature_6.xml"),  # 03: "1,False,37.5,0"
    ],
)
def test_matches_gui_script_macro(xml, fixture):
    assert macro_obj(xml) == gui_macro(fixture)
