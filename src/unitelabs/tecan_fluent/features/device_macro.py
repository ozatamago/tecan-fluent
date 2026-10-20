"""What the features of the devices driven by one legacy driver macro per command share (BioShake, Inheco
incubator, CPLC positions, Incubator1): the error, the range check and sending the macro in its own run (or the
open one).

The allowed temperature ranges are limits this connector imposes for safety (not the device specifications).
"""

from unitelabs.cdk import sila

from ..io.fluentcontrol.backend import BackendError, FluentOdtcBackend
from ..io.fluentcontrol.progress import with_progress


class TemperatureSettingFailed(Exception):
    """The temperature could not be set. The description explains why (out of range, FluentControl busy, ...)."""


def check_range(temperature: float, low: float, high: float, device: str) -> None:
    if not low <= temperature <= high:
        raise TemperatureSettingFailed(
            f"{device} accepts {low:g} to {high:g} °C (a range this connector limits for safety)"
        )


async def send_macro(backend: FluentOdtcBackend, label: str, xml: str, status: sila.Status) -> None:
    try:
        await with_progress(status, 1, lambda report: backend.run_steps([(label, xml)], report, label))
    except BackendError as exc:
        raise TemperatureSettingFailed(str(exc)) from None
