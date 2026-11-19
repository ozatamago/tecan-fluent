"""What an environment script calls to send one command to the Tecan Fluent connector inside the mission's run.

An environment script (``x-labcode.script``, ``flavor: sila2``) is the commands alone; this module adds what every
one of them must do around a command, so the scripts stay short and the same everywhere:

- refuse unless the FluentControl run that the run manager opened is still the one that is open (``RunOpen`` and
  ``RunStarted`` as recorded in ``mission.json``). A lost or replaced run is never restarted or joined here;
- record the command before it is sent and its result or error afterwards (``events.jsonl``);
- wait for the observable command to finish (``labcode.sila2_commands.settle``) with a per-command time limit.

It never resends a command and never sends a cleanup command (EndRun, DropTips, moves) after a failure: what happens
after a failure is the run manager's decision (see ``manager.py``).

Which feature and command to call, and every instrument name (labware, sites, method files), come from the
environment script and the workflow; nothing here knows the deck.

Example (an environment mode script)::

    from fluent780_labcode.steps import Step
    Step(sila2_client, cell).call("Labware", "TransferLabware", lid, location, site,
                                  label=f"{lid} -> {location}[{site}]")
"""

from __future__ import annotations

import json
import time
from typing import Any

from .cover_sites import CoverSites, name_expression
from .mission import Mission, MissionError, serializable

DEFAULT_TIMEOUT = 600.0
"""Seconds one command may take before the operation fails (as ``wait()`` in the serial test script)."""

POLL = 0.5


def _settle(instance: Any, label: str, timeout: float) -> Any:
    from labcode.sila2_commands import settle

    return settle(instance, label, timeout=timeout, poll=POLL)


class Step:
    """One operation's access to the mission's FluentControl run.

    `client` is the SiLA2 client labcode opened for the operation (``sila2_client``); `cell` is the ``Workcell``
    Object's view (it carries ``mission_dir``). `settle`, `sleep` and `cover_sites` are injectable for tests.
    """

    def __init__(self, client: Any, cell: dict, *, settle: Any = None, sleep: Any = None, cover_sites: Any = None):
        if not isinstance(cell, dict) or not cell.get("mission_dir"):
            raise MissionError("the Workcell has no mission_dir: start the workflow through the run manager")
        self.client = client
        self.mission = Mission(cell["mission_dir"])
        self.data = self.mission.data
        self._settle = settle or _settle
        self._sleep = sleep or time.sleep
        self._cover_sites = cover_sites

    # -- checks ---------------------------------------------------------------------------------------------------

    def check_run(self) -> None:
        """The mission's run must still be open and be the same run (spec S03, 3.2)."""
        run_open = self.client.RunControl.RunOpen.get()
        started = self.client.RunControl.RunStarted.get()
        if not run_open or started != self.data["run_started"]:
            self.mission.event("run_mismatch", run_open=run_open, run_started=started)
            raise MissionError(
                f"the FluentControl run of this mission is not open any more (RunOpen={run_open}, "
                f"RunStarted={started!r}, expected {self.data['run_started']!r}); nothing was sent. "
                "Do not restart it automatically: check the instrument and the deck first"
            )

    # -- commands -------------------------------------------------------------------------------------------------

    def call(self, feature: str, command: str, *args: Any, label: str | None = None, timeout: float | None = None):
        """Send ``<feature>.<command>(*args)``, wait for it, and return its responses."""
        label = label or f"{feature}.{command}{tuple(args)!r}"
        timeout = DEFAULT_TIMEOUT if timeout is None else timeout
        self.check_run()
        self.mission.event("sending", feature=feature, command=command, args=list(args), label=label)
        t0 = time.monotonic()
        try:
            responses = self._settle(getattr(getattr(self.client, feature), command)(*args), label, timeout)
        except BaseException as exc:
            # Sent, but the outcome is not known to be good: the run manager decides what follows. Never resend.
            self.mission.event(
                "failed",
                feature=feature,
                command=command,
                label=label,
                seconds=round(time.monotonic() - t0, 1),
                error=f"{type(exc).__name__}: {exc}",
            )
            raise
        self.mission.event(
            "completed",
            feature=feature,
            command=command,
            label=label,
            seconds=round(time.monotonic() - t0, 1),
            responses=serializable(responses),
        )
        return responses

    def hold(self, seconds: float, scale: float = 1.0) -> None:
        """Wait ``seconds * scale`` inside the run, checking the run before and after. `seconds` is the protocol's
        time; `scale` (e.g. 0.1 for a flow check) comes from the workflow or the run boundary."""
        actual = float(seconds) * float(scale)
        self.check_run()
        self.mission.event("hold", seconds=actual, protocol_seconds=float(seconds), scale=float(scale))
        self._sleep(actual)
        self.check_run()
        self.mission.event("held", seconds=actual)

    def wait_temperature(
        self, feature: str, command: str, minimum: float, interval: float, timeout: float, *args: Any
    ) -> float:
        """Read a temperature (``<feature>.<command>(*args)``) every `interval` seconds until it is at least
        `minimum`, and return it. Fails after `timeout` seconds; the instrument keeps its setpoint."""
        t0 = time.monotonic()
        while True:
            value = temperature_of(self.call(feature, command, *args, label=f"{feature}.{command}", timeout=180))
            self.mission.event("temperature", feature=feature, value=value, minimum=minimum)
            if value >= minimum:
                return value
            if time.monotonic() - t0 > timeout:
                raise MissionError(f"{feature}: {value} C after {timeout:.0f} s, below {minimum} C")
            self._sleep(float(interval))

    def measure(self, plate: str, method: str, *, allow_missing_result: bool = False, timeout: float = 900) -> dict:
        """``PlateHandling.MeasureWorktablePlate`` and the ``Absorbance`` value. With `allow_missing_result`, a
        measurement the server reports as done but whose result file it cannot find gives a reading with no values
        and a note (2026-11-19: Abs600.mth writes its file elsewhere) instead of failing."""
        label = f"Measure {plate} in the reader ({method})"
        try:
            responses = self.call("PlateHandling", "MeasureWorktablePlate", plate, method, label=label, timeout=timeout)
        except Exception as exc:
            text = str(exc)
            if not (allow_missing_result and "Result file" in text and "not found" in text):
                raise
            self.mission.event("note", label=label, note=text)
            return {"method": method, "result_file": "", "labels": [], "wells": [], "values": [], "note": text}
        return absorbance_reading(responses)

    # -- cover sites ----------------------------------------------------------------------------------------------

    def cover_site(self, holder: str) -> tuple[str, int]:
        """``(location, site)`` of the cover site of `holder`: the name expression and the resolved index."""
        if self._cover_sites is None:
            self._cover_sites = CoverSites(self.data.get("cover_sites"))
        index = self._cover_sites.index(holder)
        self.mission.event("cover_site", holder=holder, location=name_expression(holder), site=index)
        return name_expression(holder), index


def absorbance_reading(responses: Any) -> dict:
    """The ``Absorbance`` workflow value from a ``MeasureWorktablePlate`` response.

    The connector returns ``Result`` as a MeasurementResult structure (Method, Labels, Values of Label/Well/Value,
    ResultFile); a test server may return the same as a JSON string. Values the reader did not report (NaN) are
    left out of the reading rather than invented.
    """
    result = serializable(getattr(responses, "Result", responses))
    if isinstance(result, dict) and "Result" in result and len(result) == 1:
        result = result["Result"]
    if isinstance(result, str):
        result = json.loads(result)
    values = [v for v in result.get("Values", []) if isinstance(v.get("Value"), int | float)]
    return {
        "method": str(result.get("Method", "")),
        "result_file": str(result.get("ResultFile", "")),
        "labels": [str(v.get("Label", "")) for v in values],
        "wells": [str(v.get("Well", "")) for v in values],
        "values": [float(v["Value"]) for v in values],
        "note": "",
    }


def temperature_of(responses: Any) -> float:
    """The temperature in a ReadTemperature response (``Reading.TemperatureC``; a test server may send JSON)."""
    reading = serializable(getattr(responses, "Reading", responses))
    if isinstance(reading, dict) and "Reading" in reading and len(reading) == 1:
        reading = reading["Reading"]
    if isinstance(reading, str):
        reading = json.loads(reading)
    try:
        return float(reading["TemperatureC"])
    except (KeyError, TypeError, ValueError):
        raise MissionError(f"no temperature in {reading!r}") from None
