"""The server commands of a serial-script run, read back from its log (fixtures/colorwater_20261119_run2.log).

Each log line of a command ("<time> <label> -> <Responses> <seconds>") is turned into the command and the arguments
it was sent with, using the run boundary for the labels the log abbreviates (A, B, lid types and holders) and the
test cover-site table for the indices (the log does not print them). Lines that are not commands (waits,
temperature notes, group headers, values) are skipped; a command line that matches no rule is an error, so the
expected list cannot silently miss a command.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import yaml

TIME = re.compile(r"^\d\d:\d\d:\d\d (?:W\d\d )?")
FLOAT = r"(-?\d+(?:\.\d+)?)"
WELLS = r"(\[[^\]]*\]|[A-P]\d+)"


def _channels(text: str | None) -> list[int]:
    return [int(c) for c in text.split(",")] if text else [1]


def _wells(text: str) -> list[str]:
    return list(ast.literal_eval(text)) if text.startswith("[") else [text]


def expected_commands(log: Path, boundary: Path, cover: dict[str, int]) -> list[tuple[str, tuple]]:
    inputs = {k: v.get("view") for k, v in yaml.safe_load(boundary.read_text())["boundary"]["inputs"].items()}
    lids = {}
    for key in ("a", "b", "trough", "rack50", "rack200"):
        holder = inputs[{"a": "plate_a", "b": "plate_b"}.get(key, key)]
        lids[inputs[f"lid_{key}"]] = (inputs[f"lid_{key}_type"], holder)
    names = {"A": inputs["plate_a"], "B": inputs["plate_b"]}

    def gcn(holder: str) -> str:
        return f'GetCoverSiteName("{holder}")'

    out: list[tuple[str, tuple]] = []
    liquid_class = None
    for raw in log.read_text(encoding="utf-8").splitlines():
        if not TIME.match(raw):
            continue
        line = TIME.sub("", raw)
        if m := re.match(r"StartRun ->", line):
            out.append(("RunControl.StartRun", ()))
        elif m := re.match(r"EndRun ->", line):
            out.append(("RunControl.EndRun", ()))
        elif m := re.match(rf"CPLC slot (\d) -> {FLOAT} C ->", line):
            out.append(("CoolingHeatingPlates.SetTemperature", (int(m[1]), float(m[2]))))
        elif m := re.match(rf"BioShake -> {FLOAT} C(?: \(.*?\))? ->", line):
            out.append(("BioShake.SetTemperature", (float(m[1]),)))
        elif m := re.match(rf"Incubator1 -> {FLOAT} C ->", line):
            out.append(("Incubator1.SetTemperature", (float(m[1]),)))
        elif m := re.match(r"AddLabware (\S+) on ", line) or re.match(r"(\S+) already registered", line):
            typ, holder = lids[m[1]]
            out.append(("Labware.AddLabware", (m[1], typ, gcn(holder), cover[holder])))
        elif m := re.match(r"(.+?) -> lid of (.+?) -> TransferLabware", line):
            out.append(("Labware.TransferLabware", (m[1], gcn(m[2]), cover[m[2]])))
        elif m := re.match(r"(\S+) -> (\w+)\[(\d+)\] -> MoveLabware", line):
            out.append(("PlateTransfer.MoveLabware", (names.get(m[1], m[1]), m[2], int(m[3]))))
        elif m := re.match(r"(.+?) -> (\w+)\[(\d+)\] -> TransferLabware", line):
            out.append(("Labware.TransferLabware", (names.get(m[1], m[1]), m[2], int(m[3]))))
        elif m := re.match(r"SetNextTipPosition (.+) ([A-H]\d+) ->", line):
            out.append(("LiquidHandling.SetNextTipPosition", (m[1], m[2])))
        elif m := re.match(r"GetTips (\d+)(?: ch\[([\d, ]+)\])? from (.+?) ->", line):
            out.append(("LiquidHandling.GetTips", (f"FCA, {m[1]}ul SBS", _channels(m[2]), m[3])))
        elif m := re.match(rf"Aspirate {FLOAT}(?: x(\d+))? (.+) ([A-P]\d+) \((.+)\) ->", line):
            k = int(m[2] or 1)
            liquid_class = m[5]
            args = (m[3], [m[4]] * k, [float(m[1])] * k, liquid_class, list(range(1, k + 1)))
            out.append(("LiquidHandling.Aspirate", args))
        elif m := re.match(rf"Dispense {FLOAT} (.+) {WELLS} ->", line):
            wells = _wells(m[3])
            k = len(wells)
            args = (m[2], wells, [float(m[1])] * k, liquid_class, list(range(1, k + 1)))
            out.append(("LiquidHandling.Dispense", args))
        elif m := re.match(rf"Mix {FLOAT}x(\d+) (.+) {WELLS} ->", line):
            wells = _wells(m[4])
            k = len(wells)
            args = (m[3], wells, [float(m[1])] * k, "Water Mix", list(range(1, k + 1)), int(m[2]))
            out.append(("LiquidHandling.Mix", args))
        elif m := re.match(r"DropTips(?: ch\[([\d, ]+)\])? ->", line):
            out.append(("LiquidHandling.DropTips", (_channels(m[1]),)))
        elif re.match(r"BioShake\.ReadTemperature ->", line):
            out.append(("BioShake.ReadTemperature", ()))
        elif m := re.match(r"BioShake (LockPlate|UnlockPlate) ->", line):
            out.append((f"BioShake.{m[1]}", ()))
        elif re.match(r"BioShake temperature off ->", line):
            out.append(("BioShake.TemperatureOff", ()))
        elif re.match(r"Incubator1 CloseDoor ->", line):
            out.append(("Incubator1.CloseDoor", ()))
        elif m := re.match(rf"StartShaker {FLOAT} Hz ->", line):
            out.append(("Incubator1.StartShaker", (float(m[1]),)))
        elif re.match(r"StopShaker", line):
            out.append(("Incubator1.StopShaker", ()))
        elif m := re.match(r"photo: OK (\w+) ", line):
            out.append(("DeckCamera.TakeImage", (m[1],)))
        elif m := re.match(r"reader (\S+)(?: done|: measured)", line):
            out.append(("PlateHandling.MeasureWorktablePlate", (names["B"], m[1])))
        elif " -> " in line and "_Responses(" in line:
            raise ValueError(f"command line not understood: {raw}")
    return out


def waits(log: Path) -> list[float]:
    """The scaled waits the script made ("wait N s (...)"), in order."""
    return [float(m[1]) for m in re.finditer(r"wait (\d+(?:\.\d+)?) s \(", log.read_text(encoding="utf-8"))]
