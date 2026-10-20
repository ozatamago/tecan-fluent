"""Checks that the XML for the Inheco shaking incubator matches the macros in GUI scripts 01-07. No device access."""

import pytest

from fakes import gui_macro, macro_obj
from unitelabs.tecan_fluent.io.fluentcontrol.errors import BackendError
from unitelabs.tecan_fluent.io.inheco_incubator.macros import (
    inheco_incubator_macro_xml,
    inheco_incubator_set_temp_xml,
    inheco_incubator_shake_on_xml,
)


@pytest.mark.parametrize(
    ("xml", "fixture"),
    [
        (inheco_incubator_set_temp_xml(37), "InhecoIncubator_SetTemp_1.xml"),  # 03: "37,0.0,0"
        (inheco_incubator_set_temp_xml(25, "PT1M40S"), "InhecoIncubator_SetTemp_2.xml"),  # Sub_Cleanup: "25,0.0,0"
        (inheco_incubator_macro_xml("InhecoIncubator_Close"), "InhecoIncubator_Close_1.xml"),
        (inheco_incubator_shake_on_xml(), "InhecoIncubator_ShakeOn_1.xml"),  # 03: "14,1.0,14,1.0,180"
        (inheco_incubator_macro_xml("InhecoIncubator_ShakeOff"), "InhecoIncubator_ShakeOff_1.xml"),
    ],
)
def test_matches_gui_script_macro(xml, fixture):
    assert macro_obj(xml) == gui_macro(fixture)


def test_unlisted_moving_macros_are_refused():
    with pytest.raises(BackendError):
        inheco_incubator_macro_xml("InhecoIncubator_Open")
