"""Read the BioShake Q1's current temperature through its legacy driver macro (BioShake_GetTemp).

Like inhecoMTC_GetTemperature (io/cplc/temperature.py) and the ODTC's ReadActualTemperature, a legacy driver macro
does not return its value to ExecuteCommand: the value can only be taken from FluentControl's log. read_temperature
notes the Fluent PC time, sends BioShake_GetTemp inside the open run, and then looks in the log lines written after
that time for the device's reply.

Checked on the instrument on 2026-11-18 (16:40):

- BioShake_GetTemp with an empty <ExecutionSettings /> runs (SC_ERROR_NONE, no dialog, the run goes on).
- The driver's own channel (Tecan/Drivers/BioShake) only logs <Response status="OK" />, without the value.
- The value is in the serial traffic that the Pegasus bridge logs on Tecan/Pegasus/Pegasus/General (Severity
  "Normal") for the BioShake's port (SystemConfig.ini [BioShake] serialPort=Serial.Port03, logged as "Serial 3"):

    <note>Serial 3 at host .: <clear><color=navy;style=bold>OUT [15]<clear> getTempActual{0D}{0A} <debug>
    <note>Serial 3 at host .: <clear><color=green;style=bold>IN [11]<clear> 36.993000{0D}{0A}

  The IN line right after the OUT getTempActual line of the same port carries degrees Celsius as a decimal.
  Other ports are polled every second on the same channel (e.g. "Serial 4", the Inheco incubator: OUT
  "{0A}2{C7}T00RAT1b", IN "{B2}275{B2}"), so only the port of the BioShake is looked at, and the reading is the first
  IN that answers a getTempActual of that port after the request.

No setpoint, cached value or estimate is ever returned instead of a reading.
"""

import html
import re
import time

from ..fluentcontrol.errors import BackendError
from ..fluentcontrol.statements import legacy_macro_xml

GET_TEMP_MACRO = "BioShake_GetTemp"
GET_TEMP_SETTINGS: str | None = None
"""ExecutionSettings of BioShake_GetTemp: empty (checked on the instrument 2026-11-18)."""
VALUE_SCALE = 1.0
"""The reply is in degrees Celsius ("36.993000")."""
DEFAULT_SERIAL_PORT = 3
"""Serial port of the BioShake on the Fluent 780 (SystemConfig.ini [BioShake] serialPort=Serial.Port03)."""
PLAUSIBLE_C = (-10.0, 110.0)
"""A reply outside this range is refused (the BioShake Q1 controls 4 to 99 degrees Celsius)."""
LOG_WAIT_S = 15.0
"""How long to keep re-reading the log for the reply after the macro returned."""
SOURCE = "BioShake_GetTemp / getTempActual (driver-reported)"
TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}")
SERIAL = re.compile(r"Serial (\d+) at host [^:]*: .*?\b(OUT|IN) \[\d+\](?:<clear>)?\s*(.*?)\s*(?:<debug>)?\s*$")
"""A serial line of the Pegasus bridge: port, direction, data."""
GET_TEMP_REQUEST = re.compile(r"^getTempActual(?:\{0D\})?(?:\{0A\})?$")
REPLY_VALUE = re.compile(r"^(-?\d+(?:\.\d+)?)(?:\{0D\})?(?:\{0A\})?$")

LOG_PS1 = r"""
$d = 'C:\ProgramData\Tecan\LoggingServer\LogFiles'
# the log switches to a new file every few tens of minutes; read the current one and the one before it
$files = Get-ChildItem "$d\*.ulf","$d\*.zlf" | Sort-Object LastWriteTime -Descending | Select-Object -First 2
Add-Type -AssemblyName System.IO.Compression.FileSystem
# not sorted here: lines of the same millisecond keep the order of the file (OUT before its IN)
foreach ($f in $files) {
  if ($f.Extension -eq '.zlf') { $z = [System.IO.Compression.ZipFile]::OpenRead($f.FullName); $t = (New-Object System.IO.StreamReader($z.Entries[0].Open())).ReadToEnd(); $z.Dispose() }
  else { $fs = [System.IO.File]::Open($f.FullName,'Open','Read','ReadWrite'); $t = (New-Object System.IO.StreamReader($fs)).ReadToEnd(); $fs.Close() }
  foreach ($m in [regex]::Matches($t, '<Log [^>]*>')) {
    $tag = $m.Value
    $ts = [regex]::Match($tag, 'TimeStamp="([^"]*)"').Groups[1].Value
    if ($ts -lt '__SINCE__') { continue }
    $ch = [regex]::Match($tag, 'Channel="([^"]*)"').Groups[1].Value
    $msg = [regex]::Match($tag, 'Message="([^"]{0,600})').Groups[1].Value
    $msg = $msg -replace '&#xD;&#xA;',' ' -replace '&#xA;',' ' -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>' -replace '&quot;','"' -replace '\s+',' '
    if ($ch -like '*BioShake*' -or ($ch -like '*Pegasus*' -and $msg -like '*Serial __PORT__ at host*')) {
      $sv = [regex]::Match($tag, 'Severity="([^"]*)"').Groups[1].Value
      $ts + "`t" + $sv + "`t" + $ch + "`t" + $msg
    }
  }
}
"""  # noqa: E501 - PowerShell sent as is
"""Log lines (time, severity, channel, message; tab separated) since __SINCE__ (Fluent PC local time): the BioShake
driver's channel and the Pegasus bridge's serial lines of port __PORT__."""


def get_temp_xml() -> str:
    """The BioShake_GetTemp macro (reads only; sets nothing and does not move)."""
    return legacy_macro_xml("BioShake", GET_TEMP_MACRO, GET_TEMP_SETTINGS)


def log_script(since: str, port: int) -> str:
    if type(port) is not int or not 1 <= port <= 99:
        raise BackendError(f"Invalid BioShake serial port {port!r}")
    return LOG_PS1.replace("__SINCE__", since).replace("__PORT__", str(port))


def log_lines(text: str, since: str) -> list[tuple[str, str, str, str]]:
    """(time, severity, channel, message) of the lines LOG_PS1 returns, written at or after since, in time order
    (lines of the same millisecond keep their order; duplicates are dropped)."""
    rows, seen = [], set()
    for raw in text.splitlines():
        parts = raw.split("\t", 3)
        if len(parts) < 4 or not TIMESTAMP.fullmatch(parts[0].strip()) or parts[0].strip() < since:
            continue
        row = tuple(p.strip() for p in parts)
        if row not in seen:
            seen.add(row)
            rows.append(row)
    return sorted(rows, key=lambda r: r[0])  # stable


def parse_reading(rows: list[tuple[str, str, str, str]], port: int = DEFAULT_SERIAL_PORT) -> dict | None:
    """The first reply to a getTempActual on the BioShake's serial port in rows (from log_lines), or None if there is
    none yet.

    Raises BackendError for a reply that is not a number or is implausible: a wrong value is never returned."""
    waiting = False
    for stamp, _severity, channel, message in rows:
        if "Pegasus" not in channel:
            continue
        for _ in range(3):
            message = html.unescape(message)
        m = SERIAL.search(message)
        if not m or int(m.group(1)) != port:
            continue
        direction, data = m.group(2), m.group(3)
        if direction == "OUT":
            waiting = bool(GET_TEMP_REQUEST.match(data))
            continue
        if not waiting:
            continue
        value = REPLY_VALUE.match(data)
        if not value:
            raise BackendError(f"The BioShake's reply to getTempActual is not a number: {data[:100]}")
        celsius = float(value.group(1)) * VALUE_SCALE
        if not PLAUSIBLE_C[0] <= celsius <= PLAUSIBLE_C[1]:
            raise BackendError(f"The BioShake's temperature reply is implausible ({celsius:g} °C)")
        return {
            "temperature_c": round(celsius, 3),
            "log_timestamp": stamp,
            "source": SOURCE,
            "serial_port": port,
            "log_line": message[:300],
        }
    return None


def read_temperature(backend, report) -> dict:
    """Send one BioShake_GetTemp inside the open run and return the reply from the log. No retry, no own run."""
    if backend.config.dry_run:
        raise BackendError("The BioShake temperature cannot be read in dry-run mode; no simulated value is returned")
    if not backend.run_open:
        raise BackendError("ReadTemperature requires an open run (RunControl.StartRun); it never starts a run itself")
    port = getattr(backend.config, "bioshake_serial_port", DEFAULT_SERIAL_PORT)
    since = backend._pc_now()
    if not TIMESTAMP.fullmatch(since):
        raise BackendError(
            "Cannot read the Fluent PC time before the request, so a fresh reply could not be told apart"
        )
    script = log_script(since, port)
    found: dict = {}

    def collect() -> dict:
        deadline = time.monotonic() + LOG_WAIT_S
        rows: list = []
        while True:
            text = backend.preflight.pc.run_ps(script, 120).decode("utf-8-sig", errors="replace")
            rows = log_lines(text, since)
            try:
                value = parse_reading(rows, port)
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
        extra={"read_only_device_command": True, "bioshake_serial_port": port},
        post=collect,
    )
    if "temperature_c" in found:
        return found
    if "error" in found:
        raise BackendError(found["error"])
    lines = found.get("driver_log")
    if lines is None:
        raise BackendError("BioShake_GetTemp was sent but FluentControl's log could not be read; see the record")
    shown = " | ".join(lines[-12:]) if lines else "(no line was written)"
    raise BackendError(
        f"No reply to getTempActual on serial port {port} was found in FluentControl's log after the request "
        f"(check fluent.bioshake_serial_port). Log lines since {since}: {shown}"[:4000]
    )
