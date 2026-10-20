"""The three Inheco CPLC positions (inhecoMTC, slots 1 to 3) on the Fluent 780: heating and cooling.

The macro and the meaning of its values: io/cplc/macros.py."""

from unitelabs.cdk import sila

from ...io.cplc.macros import mtc_set_temperature_xml
from ...io.fluentcontrol.backend import FluentOdtcBackend
from ..device_macro import TemperatureSettingFailed, check_range, send_macro


class CoolingHeatingPlates(sila.Feature):
    """
    Temperature of the three Inheco CPLC positions (inhecoMTC, slots 1 to 3) on the Fluent 780.

    03_Transformation uses slot 1 at 4 degrees Celsius and slots 2 and 3 at 37, and switches all three off at the end.
    """

    LOW, HIGH = 4.0, 70.0

    def __init__(self, backend: FluentOdtcBackend):
        super().__init__(
            originator="jp.riken.bdr",
            category="inheco.cplc",
            identifier="CoolingHeatingPlates",
            name="Cooling / Heating Plates (CPLC 1-3)",
            version="1.0",
        )
        self.backend = backend
        self._last: dict[int, float] = {}

    @staticmethod
    def _slot(slot: int) -> int:
        if slot not in (1, 2, 3):
            raise TemperatureSettingFailed("Slot must be 1 to 3")
        return slot

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def set_temperature(self, slot: int, temperature: float, *, status: sila.Status) -> None:
        """
        Switch heating and cooling on for one position and set its target temperature. Returns once sent.

        Args:
          Slot: Position 1, 2 or 3.
          Temperature: Target temperature in degrees Celsius (4 to 70 in this connector).
        """
        self._slot(slot)
        check_range(temperature, self.LOW, self.HIGH, "The temperature position (inhecoMTC)")
        await send_macro(
            self.backend,
            f"inhecoMTC: slot {slot} on {temperature:.1f}",
            mtc_set_temperature_xml(slot, True, temperature),
            status,
        )
        self._last[slot] = temperature

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def turn_off(self, slot: int, *, status: sila.Status) -> None:
        """
        Switch heating and cooling off for one position.

        Args:
          Slot: Position 1, 2 or 3.
        """
        self._slot(slot)
        # Switching off still sends a temperature (same form as the GUI scripts): the last set value, else 25.0
        temperature = self._last.get(slot, 25.0)
        await send_macro(
            self.backend, f"inhecoMTC: slot {slot} off", mtc_set_temperature_xml(slot, False, temperature), status
        )
