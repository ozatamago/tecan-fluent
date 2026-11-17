"""The three Inheco CPLC positions (inhecoMTC, slots 1 to 3) on the Fluent 780: heating and cooling.

The macro and the meaning of its values: io/cplc/macros.py."""

import dataclasses

from unitelabs.cdk import sila

from ...io.cplc.macros import mtc_set_temperature_xml
from ...io.fluentcontrol.backend import BackendError, FluentControlBackend
from ..device_macro import TemperatureSettingFailed, check_range, send_macro


class TemperatureReadingFailed(Exception):
    """A fresh CPLC driver temperature could not be obtained; no estimated value is substituted."""


@dataclasses.dataclass
class CplcTemperatureReading(sila.CustomDataType):
    """A fresh driver reading, not a direct liquid measurement.

    Args:
      Slot: CPLC slot number (1 to 3).
      TemperatureC: Driver-reported temperature in degrees Celsius, including the driver's compensation.
      LogTimestamp: Fluent PC local log timestamp; not UTC and not the device's sampling timestamp.
      Source: The driver command used to obtain the value.
    """

    slot: int
    temperature_c: float
    log_timestamp: str
    source: str


class CoolingHeatingPlates(sila.Feature):
    """
    Temperature of the three Inheco CPLC positions (inhecoMTC, slots 1 to 3) on the Fluent 780.

    03_Transformation uses slot 1 at 4 degrees Celsius and slots 2 and 3 at 37, and switches all three off at the end.
    """

    LOW, HIGH = 4.0, 70.0

    def __init__(self, backend: FluentControlBackend):
        super().__init__(
            originator="jp.riken.bdr",
            category="inheco.cplc",
            identifier="CoolingHeatingPlates",
            name="Cooling / Heating Plates (CPLC 1-3)",
            version="1.0",
        )
        self.backend = backend
        self._last: dict[int, float] = {}

    @sila.ObservableCommand(errors=[TemperatureReadingFailed])
    async def read_temperature(self, slot: int, *, status: sila.Status) -> CplcTemperatureReading:
        """Read one CPLC slot without changing its setpoint, heater state, or arm position.

        Requires an existing RunControl run and the legacy driver's GetTemperature macro.
        Fails in dry-run mode and if the driver is not configured or no fresh reply is found.

        Args:
          Slot: CPLC position 1, 2 or 3.

        Returns:
          Reading: Fresh driver temperature in degrees Celsius and its log provenance.
        """
        status.update(progress=0.0)
        try:
            value = await self.backend.read_cplc_temperature(slot)
        except BackendError as exc:
            raise TemperatureReadingFailed(str(exc)) from None
        status.update(progress=1.0)
        return CplcTemperatureReading(
            slot=value["slot"],
            temperature_c=value["temperature_c"],
            log_timestamp=value["log_timestamp"],
            source=value["source"],
        )

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
