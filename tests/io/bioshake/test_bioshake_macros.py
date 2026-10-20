"""Checks that the XML for the BioShake matches the macros in GUI scripts 01-07. No device access."""

import pytest

from fakes import gui_macro, macro_obj
from unitelabs.tecan_fluent.io.bioshake.macros import (
    bioshake_macro_xml,
    bioshake_set_temp_xml,
    bioshake_shake_on_xml,
    bioshake_temp_off_xml,
)
from unitelabs.tecan_fluent.io.fluentcontrol.errors import BackendError


@pytest.mark.parametrize(
    ("xml", "fixture"),
    [
        (bioshake_set_temp_xml(4), "BioShake_SetTemp_1.xml"),  # 03: "4"
        (bioshake_temp_off_xml(), "BioShake_TempOff_1.xml"),  # 02
        (bioshake_macro_xml("BioShake_ElmLock"), "BioShake_ElmLock_1.xml"),
        (bioshake_macro_xml("BioShake_ElmUnlock"), "BioShake_ElmUnlock_1.xml"),
        (bioshake_macro_xml("BioShake_ShakeOff"), "BioShake_ShakeOff_1.xml"),
    ],
)
def test_matches_gui_script_macro(xml, fixture):
    assert macro_obj(xml) == gui_macro(fixture)


def test_bioshake_shake_on_matches_sub_skake_with_the_speed_filled_in():
    # Sub_Skake uses "~SpeedShake~,5" (the speed variable is filled in at run time)
    expected = [ln.replace("~SpeedShake~", "1400") for ln in gui_macro("BioShake_ShakeOn_2.xml")]
    assert macro_obj(bioshake_shake_on_xml(1400)) == expected


def test_unlisted_moving_macros_are_refused():
    with pytest.raises(BackendError):
        bioshake_macro_xml("BioShake_Shake")
