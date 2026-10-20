"""Incubator1 (6 Nest Incubator Shaking) on the Fluent 780: temperature, door and shaking.

The macros and the meaning of their values: io/incubator1/macros.py."""

from unitelabs.cdk import sila

from ...io.fluentcontrol.backend import FluentControlBackend
from ...io.incubator1.macros import incubator1_macro_xml, incubator1_set_temperature_xml, incubator1_start_shaker_xml
from ..device_macro import TemperatureSettingFailed, check_range, send_macro


class Incubator1(sila.Feature):
    """
    Temperature of the shaking incubator "Incubator1" (6 Nest Incubator Shaking) on the Fluent 780.

    05_Subculture_and_OD_measure sets 37 at the start and 25 at the end.
    """

    LOW, HIGH = 20.0, 50.0

    def __init__(self, backend: FluentControlBackend):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.incubator",
            identifier="Incubator1",
            name="Incubator1 - Temperature, Shaker & Door",
            version="1.0",
        )
        self.backend = backend

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def set_temperature(self, temperature: float, *, status: sila.Status) -> None:
        """
        Set the target temperature of Incubator1. Returns once the command is sent.

        Args:
          Temperature: Target temperature in degrees Celsius (20 to 50 in this connector).
        """
        check_range(temperature, self.LOW, self.HIGH, "Incubator1")
        await send_macro(
            self.backend,
            f"Incubator1: SetTemperature {temperature:g}",
            incubator1_set_temperature_xml(temperature),
            status,
        )

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def close_door(self, *, status: sila.Status) -> None:
        """Close the Incubator1 door. MOVES: keep hands out of the way."""
        await send_macro(self.backend, "Incubator1: CloseDoor", incubator1_macro_xml("Incubator1_CloseDoor"), status)

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def start_shaker(self, frequency: float, *, status: sila.Status) -> None:
        """
        Start shaking. It keeps shaking until StopShaker. MOVES.

        Args:
          Frequency: Shaking frequency in Hz, 1.0 to 8.5 (the driver's range). 05 uses 5.
        """
        if not 1.0 <= frequency <= 8.5:
            raise TemperatureSettingFailed("Incubator1 shaking must be 1.0 to 8.5 Hz (the driver's range)")
        await send_macro(
            self.backend, f"Incubator1: StartShaker {frequency:g} Hz", incubator1_start_shaker_xml(frequency), status
        )

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def stop_shaker(self, *, status: sila.Status) -> None:
        """Stop shaking. MOVES."""
        await send_macro(self.backend, "Incubator1: StopShaker", incubator1_macro_xml("Incubator1_StopShaker"), status)
