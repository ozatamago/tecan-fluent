"""The documents pass the ofplang/labcode front doors offline: lc validate, lc schedule, the labcode dialect."""

from __future__ import annotations

import subprocess
import sys

import yaml

from conftest import DOCUMENT, ENV, WORKFLOW

LC = [sys.executable, "-m", "labcode"]


def test_lc_validate_strict_portable_v0():
    result = subprocess.run([*LC, "validate", str(WORKFLOW)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr


def test_lc_schedule_plans_the_steps_in_the_scripts_order(tmp_path):
    plan = tmp_path / "plan.yaml"
    cmd = [*LC, "schedule", "schedule", str(WORKFLOW), "--env", str(ENV), "--document", str(DOCUMENT), "-o", str(plan)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    activities = [a for a in yaml.safe_load(plan.read_text())["activities"] if a.get("node")]
    order = ["/".join(a["node"]) for a in sorted(activities, key=lambda a: a["start"])]
    assert order[:5] == ["AddLidA", "AddLidB", "AddLidTrough", "AddLidRack50", "AddLidRack200"]
    assert [n for n in order if n.startswith("S") and "/" not in n] == [
        "S01_LidAToHotel", "S02_LidRack50ToNest", "S03_LidRack200ToNest", "S04_LidAOn", "S05_PlateAToBioShake",
        "S06_PlateAToCplc", "S07_LidBToHotel", "S08_LidTroughToHotel", "S09_LidTroughOn", "S10_LidRack200On",
        "S11_LidRack50On", "S12_MeasureB", "S13_LidBOn",
    ]  # fmt: skip
    assert [n.split("/", 1)[1] for n in order if n.startswith("S14_IncubateB/")] == [
        "SetTemperature", "Shake/ToRegrip", "Shake/IntoIncubator", "Shake/CloseDoor", "Shake/StartShaker",
        "Shake/Shake", "Shake/StopShaker", "Shake/BackFromIncubator", "Shake/CloseDoorAgain",
    ]  # fmt: skip
    assert len(activities) == 27


def test_labcode_dialect_front_door():
    from labcode.dialect import validate_dialect

    result = validate_dialect(yaml.safe_load(WORKFLOW.read_text()), yaml.safe_load(ENV.read_text()))
    assert result.ok, result.errors


def test_no_instrument_names_in_the_helper_package():
    from pathlib import Path

    import fluent780_labcode

    source = "".join(p.read_text() for p in Path(fluent780_labcode.__file__).parent.glob("*.py"))
    for name in (
        "Flat_Custom",
        "HotelMP_Pos",
        "Nest7mm",
        "Regrip_Pos",
        "Incub6Shake",
        "OFML_Abs405",
        "_Lid[",
        "Sarstedt",
        "Trough[",
        "ul SBS",
        "Water Free",
        "Water Mix",
        "BioShake_Q1",
        "CPLC_Flat",
    ):
        assert name not in source
