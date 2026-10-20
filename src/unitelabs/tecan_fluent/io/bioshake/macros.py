"""The XML of the BioShake Q1 macros (legacy driver macros of the BioShake driver).

The XML sent has the same form as the macros in GUI scripts 01-07 (compared character by character with
tests/fixtures/gui_macros/). The meaning of the ExecutionSettings values was inferred from the driver documentation and
from how the GUI scripts use them (2026-10-15):

- BioShake_SetTemp           "<temperature>" (e.g. "4", "4.0"). Switched off with BioShake_TempOff
- BioShake_ShakeOn           "<speed rpm>,5" (Sub_Skake). The GUI input offers speeds 1000/1200/.../2000 as choices.
                             The manual ("start shaking with speed and acceleration") suggests 5 is the acceleration,
                             but this is unconfirmed, so it is fixed
- BioShake_ShakeOff          Stops shaking, returns to the home position and locks there (manual)
- BioShake_ElmLock/Unlock    Closes / opens the plate clamp (Edge Locking Mechanism)

Verified on the device on 2026-10-15: BioShake 25 °C -> TempOff returned in 8.6-10.1 s (it does not wait for the
temperature to be reached), and the driver logged SC_ERROR_NONE.
"""

from ..fluentcontrol.errors import BackendError
from ..fluentcontrol.statements import _num, legacy_macro_xml

BIOSHAKE_SPEEDS = (1000, 1200, 1400, 1600, 1800, 2000)


def bioshake_set_temp_xml(temperature: float) -> str:
    return legacy_macro_xml("BioShake", "BioShake_SetTemp", _num(temperature))


def bioshake_temp_off_xml() -> str:
    return legacy_macro_xml("BioShake", "BioShake_TempOff", execution_time="PT0S")  # same as 02_PCR


def bioshake_macro_xml(name: str) -> str:
    if name not in ("BioShake_ElmLock", "BioShake_ElmUnlock", "BioShake_ShakeOff"):
        raise BackendError(f"{name} is not an allowed BioShake macro")
    return legacy_macro_xml("BioShake", name)


def bioshake_shake_on_xml(speed_rpm: int) -> str:
    return legacy_macro_xml("BioShake", "BioShake_ShakeOn", f"{int(speed_rpm)},5")
