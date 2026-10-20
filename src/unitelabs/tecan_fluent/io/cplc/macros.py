"""The XML of the macro for the three Inheco CPLC positions (legacy driver macro of the inhecoMTC driver).

The XML sent has the same form as the macros in GUI scripts 01-07 (compared character by character with
tests/fixtures/gui_macros/). The meaning of the ExecutionSettings values was inferred from the driver documentation and
from how the GUI scripts use them (2026-10-15):

- inhecoMTC_SetTemperature   "<slot>,<enable heating/cooling>,<temperature>,0". The settings dialog fields are
                             Slot / Enable Heater / Temperature. False switches it off (end of 03, and 06).
                             The 4th value is unknown (always 0)

Verified on the device on 2026-10-15: CPLC slot 1 25 °C -> off returned in 8.6-10.1 s (it does not wait for the
temperature to be reached), and the driver logged SC_ERROR_NONE.
"""

from ..fluentcontrol.statements import _num, legacy_macro_xml


def mtc_set_temperature_xml(slot: int, enabled: bool, temperature: float) -> str:
    return legacy_macro_xml(
        "inhecoMTC",
        "inhecoMTC_SetTemperature",
        f"{int(slot)},{'True' if enabled else 'False'},{_num(temperature, 1)},0",
    )
