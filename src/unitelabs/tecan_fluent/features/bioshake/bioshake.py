"""The BioShake Q1 (shaker with heating and cooling) on the Fluent 780: temperature, plate clamp and shaking.

The macros and the meaning of their values: io/bioshake/macros.py."""

import dataclasses

from unitelabs.cdk import sila

from ...io.bioshake.macros import (
    BIOSHAKE_SPEEDS,
    bioshake_macro_xml,
    bioshake_set_temp_xml,
    bioshake_shake_on_xml,
    bioshake_temp_off_xml,
)
from ...io.fluentcontrol.backend import BackendError, FluentControlBackend
from ..device_macro import TemperatureReadingFailed, TemperatureSettingFailed, check_range, send_macro


@dataclasses.dataclass
class BioShakeTemperatureReading(sila.CustomDataType):
    """A fresh temperature reported by the BioShake driver (the device's own sensor, not the liquid in the plate).

    Args:
      TemperatureC: Driver-reported temperature in degrees Celsius.
      LogTimestamp: Fluent PC local time of the log entry with the value; not UTC.
      Source: The driver macro the value came from.
    """

    temperature_c: float
    log_timestamp: str
    source: str


class BioShake(sila.Feature):
    """
    Temperature of the BioShake Q1 (shaker with heating and cooling) on the Fluent 780.

    Setting or reading the temperature does not move anything. LockPlate / UnlockPlate / ShakeOn / ShakeOff MOVE the
    device. ShakeOn keeps shaking until ShakeOff is sent.
    """

    LOW, HIGH = 4.0, 70.0

    def __init__(self, backend: FluentControlBackend):
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

    @sila.ObservableCommand(errors=[TemperatureReadingFailed])
    async def read_temperature(self, *, status: sila.Status) -> BioShakeTemperatureReading:
        """
        Read the BioShake's current temperature (sends BioShake_GetTemp; sets nothing and does not move).

        Requires an open run (RunControl.StartRun); it never starts a run itself. The value is taken from
        FluentControl's log after the request. Fails in dry-run mode and when no fresh value is found; a setpoint or
        estimate is never returned instead. NOT CONFIRMED ON THE INSTRUMENT YET: until the log format is confirmed it
        always fails, with the driver log lines written after the request in the error (see the README).

        Returns:
          Reading: Driver-reported temperature in degrees Celsius and the log entry it came from.
        """
        status.update(progress=0.0)
        try:
            value = await self.backend.read_bioshake_temperature()
        except BackendError as exc:
            raise TemperatureReadingFailed(str(exc)) from None
        status.update(progress=1.0)
        return BioShakeTemperatureReading(
            temperature_c=value["temperature_c"], log_timestamp=value["log_timestamp"], source=value["source"]
        )

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
