"""The BioShake Q1 (shaker with heating and cooling) on the Fluent 780: temperature, plate clamp and shaking.

The macros and the meaning of their values: io/bioshake/macros.py."""

from unitelabs.cdk import sila

from ...io.bioshake.macros import (
    BIOSHAKE_SPEEDS,
    bioshake_macro_xml,
    bioshake_set_temp_xml,
    bioshake_shake_on_xml,
    bioshake_temp_off_xml,
)
from ...io.fluentcontrol.backend import FluentOdtcBackend
from ..device_macro import TemperatureSettingFailed, check_range, send_macro


class BioShake(sila.Feature):
    """
    Temperature of the BioShake Q1 (shaker with heating and cooling) on the Fluent 780.

    Setting the temperature does not move anything. LockPlate / UnlockPlate / ShakeOn / ShakeOff MOVE the device.
    ShakeOn keeps shaking until ShakeOff is sent.
    """

    LOW, HIGH = 4.0, 70.0

    def __init__(self, backend: FluentOdtcBackend):
        super().__init__(
            originator="jp.riken.bdr",
            category="qinstruments.bioshake",
            identifier="BioShake",
            name="BioShake - Shake & Heat",
            version="1.0",
        )
        self.backend = backend

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def set_temperature(self, temperature: float, *, status: sila.Status) -> None:
        """
        Set the target temperature of the BioShake. Returns once the command is sent (it does not wait until the
        temperature is reached).

        Args:
          Temperature: Target temperature in degrees Celsius (4 to 70 in this connector). 02_PCR uses 4.
        """
        check_range(temperature, self.LOW, self.HIGH, "BioShake")
        await send_macro(self.backend, f"BioShake: SetTemp {temperature:g}", bioshake_set_temp_xml(temperature), status)

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def temperature_off(self, *, status: sila.Status) -> None:
        """Switch the BioShake's temperature control off."""
        await send_macro(self.backend, "BioShake: TempOff", bioshake_temp_off_xml(), status)

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def lock_plate(self, *, status: sila.Status) -> None:
        """Close the plate clamp (Edge Locking Mechanism). MOVES: keep fingers away."""
        await send_macro(self.backend, "BioShake: ElmLock", bioshake_macro_xml("BioShake_ElmLock"), status)

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def unlock_plate(self, *, status: sila.Status) -> None:
        """Open the plate clamp (Edge Locking Mechanism). MOVES: keep fingers away."""
        await send_macro(self.backend, "BioShake: ElmUnlock", bioshake_macro_xml("BioShake_ElmUnlock"), status)

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def shake_on(self, speed: int, *, status: sila.Status) -> None:
        """
        Start shaking. It keeps shaking until ShakeOff. MOVES. Lock the plate first if one is on the shaker.

        Args:
          Speed: Shaking speed in rpm: 1000, 1200, 1400, 1600, 1800 or 2000 (the choices of the GUI scripts).
        """
        if speed not in BIOSHAKE_SPEEDS:
            raise TemperatureSettingFailed(
                f"Speed must be one of {', '.join(map(str, BIOSHAKE_SPEEDS))} rpm (the GUI choices)"
            )
        await send_macro(self.backend, f"BioShake: ShakeOn {speed} rpm", bioshake_shake_on_xml(speed), status)

    @sila.ObservableCommand(errors=[TemperatureSettingFailed])
    async def shake_off(self, *, status: sila.Status) -> None:
        """Stop shaking; the shaker returns to its home position and locks there. MOVES."""
        await send_macro(self.backend, "BioShake: ShakeOff", bioshake_macro_xml("BioShake_ShakeOff"), status)
