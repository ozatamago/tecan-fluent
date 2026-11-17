"""Read the installed inhecoMTC driver's temperature without changing setpoints.

The legacy macro does not return its value to ExecuteCommand. Its Device.GetTemperature
log entry contains the RAT reply in tenths of a degree Celsius. Do not describe this
as a direct sample measurement or as an uncompensated PT100 value: the installed
driver sends RAT without a selector, despite the XML documentation saying PT100.
"""

import base64
import configparser
import hashlib
import html
import json
import re
import time

from ..fluentcontrol.errors import BackendError
from .macros import mtc_read_temperature_xml


def validate_slot(slot: int) -> None:
    if type(slot) is not int or slot not in (1, 2, 3):
        raise BackendError("CPLC temperature reading requires Slot 1, 2 or 3")


def check_read_macro(ini: str, slot: int) -> str:
    """Require the installed driver's known ID-to-macro mapping; never edit the INI."""
    validate_slot(slot)
    start = ini.find("[Assembly]")
    if start < 0:
        raise BackendError("The active inhecoMTC INI has no Assembly section")
    config = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        config.read_string(re.sub(r"(?m)^:[0-9]+\s*$", "", ini[start:]))
        expected = ["SetTemperature", "StartShake", "StopShake", "Shake", "GetTemperature"]
        if any(
            config.get("Macros", f"macro{i}", fallback="").strip() != "inhecoMTC_" + name
            for i, name in enumerate(expected, 1)
        ):
            raise BackendError(
                "inhecoMTC_GetTemperature is not enabled as macro5 in the active driver configuration; "
                "enable it through the supported FluentControl driver configuration first"
            )
        if not config.getboolean("Settings", f"Slot{slot}", fallback=False):
            raise BackendError(f"CPLC Slot {slot} is disabled in the active driver configuration")
    except (configparser.Error, ValueError) as exc:
        raise BackendError(f"Cannot validate the active inhecoMTC INI: {exc}") from None
    return hashlib.sha256(ini.encode("utf-8")).hexdigest()


def parse_reading(records: list[dict], slot: int, since: str) -> dict | None:
    """Accept only a fresh Device.GetTemperature completion for the requested slot."""
    validate_slot(slot)
    pattern = re.compile(
        r"\bSlotId:\s*(\d+)\s+.*?\bDevice\.GetTemperature\("
        r"[^\r\n]*\)\s*:\s*(-?\d+)\s*$"
    )
    candidates = []
    for row in records:
        timestamp = row.get("timestamp", "")
        if not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}", timestamp) or timestamp < since:
            continue
        message = row.get("message", "")
        for _ in range(4):
            message = html.unescape(message)
        match = pattern.search(message)
        if not match or int(match.group(1)) != slot:
            continue
        raw = int(match.group(2))
        if not -400 <= raw <= 1500:
            raise BackendError("CPLC driver temperature is outside the sensor plausibility range")
        candidates.append(
            {
                "slot": slot,
                "temperature_c": raw / 10.0,
                "raw_tenths_c": raw,
                "log_timestamp": timestamp,
                "source": "inhecoMTC.GetTemperature / RAT (driver-reported)",
            }
        )
    return max(candidates, key=lambda x: x["log_timestamp"]) if candidates else None


def _ps(backend, script: str) -> str:
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    return backend._ssh_ps("-EncodedCommand " + encoded)


# Read current and recent uncompressed logs only. No device, GUI, registry, or file writes.
LOG_QUERY = r"""
$ErrorActionPreference = 'Stop'
$taskDir = 'C:\ProgramData\Tecan\LoggingServer\LogFiles'
$taskRecords = @()
$taskFiles = Get-ChildItem $taskDir -Filter '*.ulf' | Sort-Object LastWriteTime -Descending | Select-Object -First 2
foreach ($taskFile in $taskFiles) {
    $taskStream = [IO.File]::Open($taskFile.FullName, 'Open', 'Read', 'ReadWrite')
    try {
        $taskReader = New-Object IO.StreamReader($taskStream)
        $taskText = $taskReader.ReadToEnd()
    } finally { $taskStream.Dispose() }
    foreach ($taskMatch in [regex]::Matches($taskText, '<Log\b[^>]*\bTimeStamp="([^"]+)"[^>]*\bMessage="([^"]*)"')) {
        if ($taskMatch.Groups[1].Value -ge '__SINCE__' -and $taskMatch.Groups[2].Value -match 'Device.GetTemperature') {
            $taskRecords += @{timestamp=$taskMatch.Groups[1].Value;message=$taskMatch.Groups[2].Value}
        }
    }
}
ConvertTo-Json -InputObject @($taskRecords) -Depth 3 -Compress
"""


def read_temperature(backend, slot: int, report) -> dict:
    """Send one read macro inside an existing run; no auto-initialization or retry."""
    validate_slot(slot)
    if backend.config.dry_run:
        raise BackendError("Actual CPLC temperature is unavailable in dry-run mode; no simulated value is returned")
    if not backend.run_open:
        raise BackendError("ReadTemperature requires an already open RunControl run; it never starts a method itself")
    path = backend.config.cplc_driver_ini
    if "'" in path or "\n" in path or "\r" in path:
        raise BackendError("Invalid CPLC driver INI path")
    ini = _ps(backend, f"Get-Content -LiteralPath '{path}' -Raw")
    ini_hash = check_read_macro(ini, slot)
    since = _ps(backend, "Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'").strip()
    if not re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3}", since):
        raise BackendError("Cannot establish the Fluent PC timestamp before the temperature request")
    reading = {}

    def collect():
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            rows = json.loads(_ps(backend, LOG_QUERY.replace("__SINCE__", since)))
            if not isinstance(rows, list):
                raise BackendError("Unexpected CPLC log query response")
            value = parse_reading(rows, slot, since)
            if value is not None:
                reading.update(value)
                return {"cplc_temperature": value}
            time.sleep(0.5)
        raise BackendError("No fresh CPLC temperature reply for the requested slot was found in the driver log")

    backend._run_steps(
        [(f"inhecoMTC: ReadTemperature slot {slot}", mtc_read_temperature_xml(slot))],
        report,
        extra={"read_only_device_command": True, "cplc_slot": slot, "driver_ini_text_sha256": ini_hash},
        post=collect,
    )
    # _run_steps records post errors without raising. A read API must fail if no actual value was collected.
    if not reading:
        raise BackendError("CPLC read command completed but no fresh temperature value was obtained; see the record")
    return reading
