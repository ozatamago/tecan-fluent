"""The XML of the Incubator1 macros (6 Nest Incubator Shaking, legacy driver macros of the Incubator1 driver).

The XML sent has the same form as the macros in GUI scripts 01-07 (compared character by character with
tests/fixtures/gui_macros/). The meaning of the ExecutionSettings values was inferred from the driver documentation and
from how the GUI scripts use them (2026-10-15):

- Incubator1_SetTemperature  "0,<temperature>". 05 sets it back to 25 at the end. The leading 0 appears to mean
                             "all positions" (2026-10-15: after one call the driver logged a setting for each of
                             the 6 positions)
- Incubator1_StartShaker     "<frequency Hz>". The driver accepts 1.0-8.5 Hz (string in the driver binary). 05 uses 5

Verified on the device on 2026-10-15: Incubator1 25 °C returned in 8.6-10.1 s (it does not wait for the temperature to
be reached), and the driver logged SC_ERROR_NONE.
"""

from ..fluentcontrol.errors import BackendError
from ..fluentcontrol.statements import _num, legacy_macro_xml


def incubator1_set_temperature_xml(temperature: float) -> str:
    return legacy_macro_xml("Incubator1", "Incubator1_SetTemperature", f"0,{_num(temperature)}")


def incubator1_macro_xml(name: str) -> str:
    if name not in ("Incubator1_CloseDoor", "Incubator1_StopShaker"):
        raise BackendError(f"{name} is not an allowed Incubator1 macro")
    return legacy_macro_xml("Incubator1", name)


def incubator1_start_shaker_xml(frequency_hz: float) -> str:
    return legacy_macro_xml("Incubator1", "Incubator1_StartShaker", _num(frequency_hz))
