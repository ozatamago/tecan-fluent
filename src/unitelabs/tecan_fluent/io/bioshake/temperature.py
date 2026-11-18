"""Read the BioShake Q1's current temperature through its legacy driver macro (BioShake_GetTemp).

Like inhecoMTC_GetTemperature (io/cplc/temperature.py) and the ODTC's ReadActualTemperature, a legacy driver macro
does not return its value to ExecuteCommand: the value can only be taken from FluentControl's log. read_temperature
notes the Fluent PC time, sends BioShake_GetTemp inside the open run, and then looks in the log lines written after
that time for the line carrying the value.

NOT CONFIRMED ON THE INSTRUMENT YET. No GUI script (01-07, Sub_*) uses BioShake_GetTemp, so there is no template in
tests/fixtures/gui_macros/, and no log of a BioShake_GetTemp has been read. Three things are therefore unknown, and
are kept in the constants below so that one check on the instrument is enough to fill them in:

- GET_TEMP_SETTINGS   The ExecutionSettings of BioShake_GetTemp. None sends an empty <ExecutionSettings /> (as
                      BioShake_ElmLock / ElmUnlock / ShakeOff in the GUI scripts). The driver may instead expect an
                      output variable, as inhecoMTC_GetTemperature does ("<slot>,,0").
- TEMPERATURE_LINE    The log line with the value (a regular expression with a group named "value", matched against
                      "<channel> <message>"). None: the format is unknown, so no value is ever returned.
- VALUE_SCALE         The factor from the logged number to degrees Celsius (the CPLC driver logs tenths).

Until TEMPERATURE_LINE is set, ReadTemperature still sends the macro (when called) but fails, and the error and the
operation's record contain the driver log lines written after the request: these are what is needed to fill in the
constants. No setpoint, cached value or estimate is ever returned instead of a reading.
"""

import re
import time

from ..fluentcontrol.errors import BackendError
from ..fluentcontrol.statements import legacy_macro_xml

GET_TEMP_MACRO = "BioShake_GetTemp"
GET_TEMP_SETTINGS: str | None = None
"""UNCONFIRMED: ExecutionSettings of BioShake_GetTemp (None: empty)."""
TEMPERATURE_LINE: re.Pattern[str] | None = None
"""UNCONFIRMED: the log line carrying the value, with a group named "value" (None: format unknown)."""
VALUE_SCALE = 1.0
"""UNCONFIRMED: logged number * VALUE_SCALE = degrees Celsius."""
PLAUSIBLE_C = (-10.0, 110.0)
"""A logged value outside this range is refused (the BioShake Q1 controls 4 to 99 degrees Celsius)."""
LOG_WAIT_S = 15.0
"""How long to keep re-reading the log for the value after the macro returned."""
SOURCE = "BioShake_GetTemp (driver-reported)"
TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}")

LOG_PS1 = r"""
$d = 'C:\ProgramData\Tecan\LoggingServer\LogFiles'
# the log switches to a new file every few tens of minutes; read the current one and the one before it
$files = Get-ChildItem "$d\*.ulf","$d\*.zlf" | Sort-Object LastWriteTime -Descending | Select-Object -First 2
Add-Type -AssemblyName System.IO.Compression.FileSystem
$out = foreach ($f in $files) {
  if ($f.Extension -eq '.zlf') { $z = [System.IO.Compression.ZipFile]::OpenRead($f.FullName); $t = (New-Object System.IO.StreamReader($z.Entries[0].Open())).ReadToEnd(); $z.Dispose() }
  else { $fs = [System.IO.File]::Open($f.FullName,'Open','Read','ReadWrite'); $t = (New-Object System.IO.StreamReader($fs)).ReadToEnd(); $fs.Close() }
  foreach ($m in [regex]::Matches($t, '<Log [^>]*>')) {
    $tag = $m.Value
    $ts = [regex]::Match($tag, 'TimeStamp="([^"]*)"').Groups[1].Value
    if ($ts -lt '__SINCE__') { continue }
    $ch = [regex]::Match($tag, 'Channel="([^"]*)"').Groups[1].Value
    $msg = [regex]::Match($tag, 'Message="([^"]{0,600})').Groups[1].Value
    if ($ch -like '*BioShake*' -or $msg -like '*BioShake*' -or $ch -like '*Legacy*' -or $ch -like '*Application Driver*') {
      $sv = [regex]::Match($tag, 'Severity="([^"]*)"').Groups[1].Value
      $msg = $msg -replace '&#xD;&#xA;',' ' -replace '&#xA;',' ' -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>' -replace '&quot;','"' -replace '\s+',' '
      $ts + "`t" + $sv + "`t" + $ch + "`t" + $msg
    }
  }
}
$out | Sort-Object -Unique
"""  # noqa: E501 - PowerShell sent as is
"""Log lines (time, severity, channel, message; tab separated) since __SINCE__ (Fluent PC local time) that may carry
the BioShake driver's reply: lines of channels or messages naming the BioShake, and of the legacy / application
drivers."""


def get_temp_xml() -> str:
    """The BioShake_GetTemp macro (reads only; sets nothing and does not move)."""
    return legacy_macro_xml("BioShake", GET_TEMP_MACRO, GET_TEMP_SETTINGS)


def log_lines(text: str, since: str) -> list[tuple[str, str, str, str]]:
    """(time, severity, channel, message) of the lines LOG_PS1 returns, written at or after since, in order."""
    rows = []
    for raw in text.splitlines():
        parts = raw.split("\t", 3)
        if len(parts) < 4 or not TIMESTAMP.fullmatch(parts[0].strip()) or parts[0].strip() < since:
            continue
        rows.append(tuple(p.strip() for p in parts))
    return sorted(rows, key=lambda r: r[0])


def parse_reading(
    rows: list[tuple[str, str, str, str]],
    pattern: re.Pattern[str] | None = None,
    scale: float | None = None,
) -> dict | None:
    """The first value after the request (rows from log_lines), or None if no line matches (or the format is unknown).

    Raises BackendError for a matching line whose value is not a number or is implausible: a wrong value is never
    returned."""
    pattern = TEMPERATURE_LINE if pattern is None else pattern
    scale = VALUE_SCALE if scale is None else scale
    if pattern is None:
        return None
    for stamp, _severity, channel, message in rows:
        m = pattern.search(f"{channel} {message}")
        if not m:
            continue
        try:
            value = float(m.group("value")) * scale
        except (IndexError, ValueError):
            raise BackendError(f"The BioShake temperature in the log is not a number: {message[:200]}") from None
        if not PLAUSIBLE_C[0] <= value <= PLAUSIBLE_C[1]:
            raise BackendError(f"The BioShake temperature in the log is implausible ({value:g} °C): {message[:200]}")
        return {"temperature_c": round(value, 2), "log_timestamp": stamp, "source": SOURCE, "log_line": message[:300]}
    return None


def read_temperature(backend, report) -> dict:
    """Send one BioShake_GetTemp inside the open run and return the value from the log. No retry, no own run."""
    if backend.config.dry_run:
        raise BackendError("The BioShake temperature cannot be read in dry-run mode; no simulated value is returned")
    if not backend.run_open:
        raise BackendError("ReadTemperature requires an open run (RunControl.StartRun); it never starts a run itself")
    since = backend._pc_now()
    if not TIMESTAMP.fullmatch(since):
        raise BackendError(
            "Cannot read the Fluent PC time before the request, so a fresh reply could not be told apart"
        )
    found: dict = {}

    def collect() -> dict:
        deadline = time.monotonic() + LOG_WAIT_S
        rows: list = []
        while True:
            text = backend.preflight.pc.run_ps(LOG_PS1.replace("__SINCE__", since), 120).decode(
                "utf-8-sig", errors="replace"
            )
            rows = log_lines(text, since)
            try:
                value = parse_reading(rows)
            except BackendError as exc:
                found["error"] = str(exc)
                return {"bioshake_read_error": str(exc)}
            if value is not None:
                found.update(value)
                return {"bioshake_temperature": value}
            if time.monotonic() >= deadline:
                break
            report("waiting for the BioShake temperature in the log")
            time.sleep(1.0)
        found["driver_log"] = ["\t".join(r) for r in rows[-40:]]
        return {"bioshake_driver_log": found["driver_log"]}

    backend._run_steps(
        [("BioShake: GetTemp", get_temp_xml())],
        report,
        extra={"read_only_device_command": True, "bioshake_log_format_confirmed": TEMPERATURE_LINE is not None},
        post=collect,
    )
    if "temperature_c" in found:
        return found
    if "error" in found:
        raise BackendError(found["error"])
    lines = found.get("driver_log")
    if lines is None:
        raise BackendError("BioShake_GetTemp was sent but FluentControl's log could not be read; see the record")
    what = (
        "The log line carrying the BioShake temperature is not known yet (io/bioshake/temperature.py, TEMPERATURE_LINE)"
        if TEMPERATURE_LINE is None
        else "No BioShake temperature was found in FluentControl's log after the request"
    )
    shown = " | ".join(lines[-12:]) if lines else "(no driver log line was written)"
    raise BackendError(f"{what}. Driver log lines since {since}: {shown}"[:4000])
