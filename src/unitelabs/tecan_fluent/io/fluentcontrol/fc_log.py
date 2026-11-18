"""What FluentControl actually did, read from its log (C:\\ProgramData\\Tecan\\LoggingServer\\LogFiles).

A Smart Command (Reagent Distribution, Sample Transfer, Transfer Individual Volumes) or a worklist is expanded by
FluentControl into ordinary statements ("Smart Subroutine ...: Line 2 : Get Tips (FCA 1)"), and the API returns
nothing about them. The log has, per expanded line, the labware, the well indexes, the volume per channel, the tip
position taken and the volume really aspirated (with the liquid class's corrections). expanded_steps() turns these
log entries into one dict per line (2026-10-16: checked against Reagent Distribution, Sample Transfer, Transfer
Individual Volumes and a worklist on the instrument).
"""

import re

LOG_PS1 = r"""
$d = 'C:\ProgramData\Tecan\LoggingServer\LogFiles'
# the log switches to a new file every few tens of minutes; read the current one and the one before it
$files = Get-ChildItem "$d\*.ulf","$d\*.zlf" | Sort-Object LastWriteTime -Descending | Select-Object -First 2
Add-Type -AssemblyName System.IO.Compression.FileSystem
$out = foreach ($f in $files) {
  if ($f.Extension -eq '.zlf') { $z = [System.IO.Compression.ZipFile]::OpenRead($f.FullName); $t = (New-Object System.IO.StreamReader($z.Entries[0].Open())).ReadToEnd(); $z.Dispose() }
  else { $fs = [System.IO.File]::Open($f.FullName,'Open','Read','ReadWrite'); $t = (New-Object System.IO.StreamReader($fs)).ReadToEnd(); $fs.Close() }
  foreach ($m in [regex]::Matches($t, '<Log [^>]*TimeStamp="([0-9-]+ [0-9:.]+)"[^>]*Message="([^"]{0,2500})')) {
    $msg = $m.Groups[2].Value -replace '&#xD;&#xA;',' ' -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>' -replace '&quot;','"' -replace '\s+',' '
    if ($m.Groups[1].Value -ge '__SINCE__' -and $msg -match 'Line \d+ : |Execution parameters for|Variable: aspirationVolume Scope|detected volume|: Filter ') {
      $m.Groups[1].Value + "`t" + $msg
    }
  }
}
$out | Sort-Object -Unique
"""  # noqa: E501 - PowerShell sent as is

STEP = re.compile(r":Line (\d+) : (.+?) \((?:FCA|LiHa|LIHA)[^)]*\)\s*$")
PARAMS = re.compile(r"Execution parameters for '([^']+)' at line (\d+): (.*)")
ASPIRATED = re.compile(r"Variable: aspirationVolume Scope: channel(\d+)\|.*? Value: ([0-9.]+)")


def well_name(index: int, rows: int) -> str:
    """FluentControl's well index (0, down the columns) as a name like "B3"."""
    return f"{chr(ord('A') + index % rows)}{index // rows + 1}"


def expanded_steps(log_text: str) -> list[dict]:
    """One dict per expanded line, in order: line, action, labware, well_indexes, volumes ({channel: ul}),
    tip_rack / tip_index (Get Tips), aspirated ({channel: ul}, Aspirate)."""
    steps: list[dict] = []
    current: dict | None = None
    for raw in log_text.splitlines():
        if "\t" not in raw:
            continue
        stamp, msg = raw.split("\t", 1)
        m = STEP.search(msg)
        if m:
            current = {"time": stamp, "line": int(m.group(1)), "action": m.group(2)}
            steps.append(current)
            continue
        if current is None:
            continue
        m = PARAMS.search(msg)
        if m and m.group(1) == current["action"]:
            body = m.group(3)
            lab = re.search(r"(?:^| )Labware: (.+?) Tip Selection", body)
            if lab:
                current["labware"] = lab.group(1)
            wells = re.search(r"Selection of Wells: ([0-9, ]+?) Well Offset", body)
            if wells:
                current["well_indexes"] = [int(x) for x in re.findall(r"\d+", wells.group(1))]
            vols = re.search(r"Volumes: (.*?)(?:Liquid Classes:|X offset|$)", body)
            if vols:
                current["volumes"] = {
                    int(c) + 1: float(v) for c, v in re.findall(r"\((\d+), ([0-9.]+)\)", vols.group(1)) if float(v) > 0
                }
            lc = re.search(r"Liquid class: (.+?) (?:Volumes:|$)", body)
            if lc:
                current["liquid_class"] = lc.group(1)
            if current["action"] == "Get Tips":
                rack = re.search(r"ModifiedLabware: (.+?) Modified", body)
                tip = re.search(r"ModifiedSelectedWellIndexes: ([0-9, ]+?) Modified", body)
                if rack:
                    current["tip_rack"] = rack.group(1)
                if tip:
                    current["tip_indexes"] = [int(x) for x in re.findall(r"\d+", tip.group(1))]
            continue
        m = ASPIRATED.search(msg)
        if m and current["action"] == "Aspirate":
            current.setdefault("aspirated", {})[int(m.group(1))] = round(float(m.group(2)), 2)
    return steps


def tips_taken(log_text: str) -> dict[str, list[int]]:
    """Tip positions FluentControl took, per rack (well indexes, column-major from 0), from the "Execution parameters
    for 'Get Tips'" entries of the log text LOG_PS1 returns. Unlike expanded_steps it does not need the "Line n :"
    entry of an expanded line, so it also covers a GetTips sent on its own."""
    taken: dict[str, list[int]] = {}
    for raw in log_text.splitlines():
        m = PARAMS.search(raw)
        if not m or m.group(1) != "Get Tips":
            continue
        rack = re.search(r"ModifiedLabware: (.+?) Modified", m.group(3))
        tips = re.search(r"ModifiedSelectedWellIndexes: ([0-9, ]+?)(?: Modified|\s*$)", m.group(3))
        if rack and tips:
            taken.setdefault(rack.group(1).strip(), []).extend(int(x) for x in re.findall(r"\d+", tips.group(1)))
    return taken


def describe(steps: list[dict], rows_of) -> list[str]:
    """Readable lines, e.g. "3 Aspirate 4 Well SBS Trough[001] A1: 90 ul (takes up 116.97 ul)". rows_of(labware)
    gives the rows of a labware (None if unknown: indexes are then shown as numbers)."""

    def wells(labware, indexes):
        rows = rows_of(labware) if labware else None
        return ",".join(well_name(i, rows) if rows else f"#{i}" for i in indexes)

    out = []
    for s in steps:
        text = f"{s['line']} {s['action']}"
        if s["action"] == "Get Tips" and s.get("tip_rack"):
            text += f" from {s['tip_rack']} {wells(s['tip_rack'], s.get('tip_indexes', []))}"
        elif s.get("labware"):
            text += f" {s['labware']}"
            if s.get("well_indexes") and "Drop Tips" not in s["action"]:
                text += f" {wells(s['labware'], s['well_indexes'])}"
        if s.get("volumes"):
            text += ": " + ", ".join(
                f"{v:g} ul" + (f" (ch{c})" if len(s["volumes"]) > 1 else "") for c, v in sorted(s["volumes"].items())
            )
        if s.get("aspirated"):
            text += " (takes up " + ", ".join(f"{v:g}" for _, v in sorted(s["aspirated"].items())) + " ul)"
        out.append(text)
    return out


# ---- Did an RGA move (RGA1_TransferLabware) really run?
# On 2026-11-18 (11:28, 11:39, 11:46) ExecuteCommand of an RGA1_TransferLabware that would have put a lid onto the cover
# site it already occupied returned after 0.015 s, but FluentControl only logged "Received command", "Execute Checks is
# started" and "RecoveryHandler ... created": the move never started and the run waited until it was stopped by hand.
# A move that runs logs "Move <label> from <location> position <n> ... to <location> position <n> ..." on the channel
# ".../Application Driver/RGA 1" within a fraction of a second; a failed one logs "Execution of move failed" there.

RGA_LOG_PS1 = r"""
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
    $msg = [regex]::Match($tag, 'Message="([^"]{0,400})').Groups[1].Value
    if ($msg.StartsWith('Received command') -or $ch -like '*Application Driver*' -or $msg -like '*move failed*') {
      $sv = [regex]::Match($tag, 'Severity="([^"]*)"').Groups[1].Value
      $msg = $msg -replace '&#xD;&#xA;',' ' -replace '&#xA;',' ' -replace '&amp;','&' -replace '&lt;','<' -replace '&gt;','>' -replace '&quot;','"' -replace '\s+',' '
      $ts + "`t" + $sv + "`t" + $ch + "`t" + $msg
    }
  }
}
$out | Sort-Object -Unique
"""  # noqa: E501 - PowerShell sent as is
"""Log lines (time, severity, channel, message; tab separated) since __SINCE__ (PC local time) that tell whether an RGA
move ran: the commands received over the API and what the application drivers (RGA 1) logged."""

RGA_MACRO = "RGA1_TransferLabware"
RGA_MOVE = re.compile(r"^Move (.+?) from (.+?) to (.+?)(?:\.|$)")
RGA_LABWARE = re.compile(r"Labware&(?:amp;)*gt;(.*?)&(?:amp;)*lt;/Labware&")


def rga_labware(xml: str) -> str:
    """The labware an RGA1_TransferLabware statement moves ("" if it cannot be found)."""
    m = RGA_LABWARE.search(xml)
    return m.group(1).strip() if m else ""


def rga_move_outcome(log_text: str, labware: str = "") -> dict:
    """What the log (lines from RGA_LOG_PS1, read from just before the command was sent) says about the first
    RGA1_TransferLabware received in it.

    status: "moved" (a "Move <labware> from ... to ..." line followed it), "failed" ("Execution of move failed", or
    the RGA moved other labware), "not_moved" (received, but no move was logged) or "not_logged" (no RGA command was
    received in the log yet). Lines after the next received command are not looked at."""
    received = ""
    move: dict | None = None
    failures: list[str] = []
    for raw in log_text.splitlines():
        parts = raw.split("\t", 3)
        if len(parts) < 4:
            continue
        stamp, severity, channel, msg = (p.strip() for p in parts)
        if msg.startswith("Received command"):
            if received:
                break  # the next command
            if RGA_MACRO in msg:
                received = stamp
            continue
        if not received:
            continue
        m = RGA_MOVE.match(msg)
        if m and "RGA" in channel and move is None:
            move = {"time": stamp, "labware": m.group(1), "from": m.group(2), "to": m.group(3)}
        elif "move failed" in msg.lower() and "Application Driver" in channel and severity in ("Error", "Critical"):
            failures.append(f"{stamp} {msg}")
    if not received:
        return {"status": "not_logged"}
    result: dict = {"status": "moved", "received": received}
    if move is not None:
        result["move"] = move
    if failures:
        result["status"] = "failed"
        result["errors"] = failures[:5]
    elif move is None:
        result["status"] = "not_moved"
    elif labware and move["labware"] != labware:
        result["status"] = "failed"
        result["errors"] = [f"the RGA moved {move['labware']}, not {labware}"]
    return result
