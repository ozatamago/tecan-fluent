"""The XML of the Inheco Incubator Shaker DWP macros (legacy driver macros of the InhecoIncubator driver).

The XML sent has the same form as the macros in GUI scripts 01-07 (compared character by character with
tests/fixtures/gui_macros/). The meaning of the ExecutionSettings values was inferred from the driver documentation and
from how the GUI scripts use them (2026-10-15):

- InhecoIncubator_SetTemp    "<temperature>,0.0,0". The 2nd and 3rd values are unknown (scripts always use 0.0,0).
                             Sub_Cleanup sets it back to 25
- InhecoIncubator_ShakeOn    "14,1.0,14,1.0,180" (03). The meaning is unknown, so only this one setting is sent

Verified on the device on 2026-10-15: Inheco 25 °C returned in 8.6-10.1 s (it does not wait for the temperature to be
reached), and the driver logged SC_ERROR_NONE.
"""

from ..fluentcontrol.errors import BackendError
from ..fluentcontrol.statements import _num, legacy_macro_xml

INHECO_SHAKE_PRESET = "14,1.0,14,1.0,180"


def inheco_incubator_set_temp_xml(temperature: float, execution_time: str = "PT2S") -> str:
    return legacy_macro_xml("InhecoIncubator", "InhecoIncubator_SetTemp", f"{_num(temperature)},0.0,0", execution_time)


def inheco_incubator_macro_xml(name: str) -> str:
    if name not in ("InhecoIncubator_Close", "InhecoIncubator_ShakeOff"):
        raise BackendError(f"{name} is not an allowed Inheco incubator macro")
    return legacy_macro_xml("InhecoIncubator", name)


def inheco_incubator_shake_on_xml() -> str:
    return legacy_macro_xml("InhecoIncubator", "InhecoIncubator_ShakeOn", INHECO_SHAKE_PRESET)
