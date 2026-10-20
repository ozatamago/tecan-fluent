"""The Inheco Incubator Shaker DWP on the Fluent 780: temperature, drawer and shaking.

The macros and the meaning of their values: io/inheco_incubator/macros.py."""

from unitelabs.cdk import sila

from ...io.fluentcontrol.backend import FluentControlBackend
from ...io.inheco_incubator.macros import (
    inheco_incubator_macro_xml,
    inheco_incubator_set_temp_xml,
    inheco_incubator_shake_on_xml,
)
from ..device_macro import TemperatureSettingFailed, check_range, send_macro


class ShakingIncubator(sila.Feature):
    """
    Temperature of the Inheco Incubator Shaker DWP on the Fluent 780.

    There is no "off" command in the GUI scripts; their cleanup sets 25 degrees Celsius.
    """

    LOW, HIGH = 20.0, 60.0

    def __init__(self, backend: FluentControlBackend):
        super().__init__(
            originator="jp.riken.bdr",
            category="inheco.incubator",
            identifier="ShakingIncubator",
            name="Inheco Incubator - Shake & Heat",
            version="1.0",
        )
        self.backend = backend

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def set_temperature(self, temperature: float, *, status: sila.Status) -> None:
        """
        Set the target temperature of the incubator. Returns once the command is sent.

        Args:
          Temperature: Target temperature in degrees Celsius (20 to 60 in this connector). 03 uses 37, cleanup 25.
        """
        check_range(temperature, self.LOW, self.HIGH, "The Inheco shaking incubator")
        await send_macro(
            self.backend,
            f"InhecoIncubator: SetTemp {temperature:g}",
            inheco_incubator_set_temp_xml(temperature),
            status,
        )

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def close(self, *, status: sila.Status) -> None:
        """Close the incubator drawer. MOVES: keep hands and plates out of the way."""
        await send_macro(
            self.backend, "InhecoIncubator: Close", inheco_incubator_macro_xml("InhecoIncubator_Close"), status
        )

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def shake_on(self, *, status: sila.Status) -> None:
        """
        Start shaking with the setting used by 03_Transformation ("14,1.0,14,1.0,180"; the meaning of the values is
        not documented, so only this setting is offered). It keeps shaking until ShakeOff. MOVES.
        """
        await send_macro(self.backend, "InhecoIncubator: ShakeOn", inheco_incubator_shake_on_xml(), status)

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def shake_off(self, *, status: sila.Status) -> None:
        """Stop shaking. MOVES."""
        await send_macro(
            self.backend, "InhecoIncubator: ShakeOff", inheco_incubator_macro_xml("InhecoIncubator_ShakeOff"), status
        )
