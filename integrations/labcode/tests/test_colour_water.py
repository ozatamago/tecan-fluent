"""W01-W21 (colour_water_w01_w21.workflow.yaml) with the in-process fake SiLA2 client.

The expected server commands are read from the log of the run that passed on the real Fluent 780 on 2026-11-19
17:21-17:57 (fixtures/colorwater_20261119_run2.log, see runlog.py).
"""

from __future__ import annotations

import subprocess
import sys

import pytest
import yaml
from fluent780_labcode import mission as m
from fluent780_labcode import steps as steps_module
from fluent780_labcode.mission import Mission, MissionError
from fluent780_labcode.pipetting import Pipetting, wells_by_column
from fluent780_labcode.steps import Step
from runlog import expected_commands, waits

from conftest import COVER, ENV, HERE, WORKFLOWS
from fakes import FakeClient, FakeInstrument, run_mission

WORKFLOW = WORKFLOWS / "colour_water_w01_w21.workflow.yaml"
BOUNDARY = WORKFLOWS / "colour_water_w01_w21.boundary.yaml"
DOCUMENT = WORKFLOWS / "fluent780.document.yaml"
LOG = HERE / "fixtures" / "colorwater_20261119_run2.log"
EXPECTED = expected_commands(LOG, BOUNDARY, COVER)
END = ("RunControl.EndRun", ())

# The racks' next tips at the start of the 2026-11-19 run: the 50 ul rack's is in the log (SetNextTipPosition D4);
# the 200 ul and 1000 ul ones follow from how the log split the multi-channel groups (200: a fresh column, so two
# tips are left after the six single tips; 1000: seven tips left in the column).
TIPS = {"FCA_ 50ul SBS[001]": "D4", "FCA_ 200ul SBS[003]": "A3", "FCA_ 1000ul SBS[002]": "B2"}


def already_registered(feature, command, args):
    # The rack lids were already in FluentControl's record from the deck state on 2026-11-19.
    if command == "AddLabware" and args[0] in ("Rack50_Lid[001]", "Rack200_Lid[001]"):
        return f"{args[0]} already exists"
    return None


def instrument(fail=already_registered, **kw):
    kw.setdefault("tips", TIPS)
    kw.setdefault("missing_results", {"Abs600.mth"})
    return FakeInstrument(fail=fail, **kw)


@pytest.fixture(autouse=True)
def no_real_waits(monkeypatch):
    slept = []
    monkeypatch.setattr(steps_module.time, "sleep", lambda s: slept.append(s))
    return slept


def run(tmp_path, config, inst, **kw):
    return run_mission(tmp_path / "mission", {**config, **kw}, inst, WORKFLOW, ENV, BOUNDARY)


def test_documents_pass_lc_validate_and_lc_schedule(tmp_path):
    lc = [sys.executable, "-m", "labcode"]
    assert subprocess.run([*lc, "validate", str(WORKFLOW)], capture_output=True, check=False).returncode == 0
    plan = tmp_path / "plan.yaml"
    cmd = [*lc, "schedule", "schedule", str(WORKFLOW), "--env", str(ENV), "--document", str(DOCUMENT), "-o", str(plan)]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    activities = [a for a in yaml.safe_load(plan.read_text())["activities"] if a.get("node")]
    order = ["/".join(a["node"]) for a in sorted(activities, key=lambda a: a["start"])]
    steps = [n.split("_")[0] for n in order]
    assert steps == sorted(steps, key=lambda s: ("WRE".index(s[0]), s))  # W01 ... W21, reader, end
    assert len(activities) == 75


def test_the_server_receives_the_commands_of_the_real_run_in_order(tmp_path, config, no_real_waits):
    inst = instrument()
    code, mission, _ = run(tmp_path, config, inst)

    assert code == 0, mission.state()
    assert inst.sila_calls() == EXPECTED
    assert len(EXPECTED) == 236  # 233 commands in the run (EndRun reported 233), StartRun, EndRun and the photo
    # the waits: the protocol's times x 0.1 as in the log, and the unscaled 10 s shake
    holds = [e["seconds"] for e in mission.events() if e["kind"] == "hold"]
    assert holds == [*waits(LOG), 10.0]
    assert mission.state()["state"] == m.COMPLETED and not inst.run_open
    notes = [e["note"] for e in mission.events() if e["kind"] == "note"]
    assert len(notes) == 1 and "Abs600.mth" in notes[0] and "not found" in notes[0]


def test_multi_channel_groups_follow_the_plate_columns_and_split_at_the_rack_column(tmp_path, config):
    inst = instrument()
    run(tmp_path, config, inst)
    gets = [args for command, args in inst.sila_calls() if command == "LiquidHandling.GetTips"]
    k1000 = [len(ch) for _, ch, rack in gets if rack.startswith("FCA_ 1000ul")]
    k200 = [len(ch) for _, ch, rack in gets if rack.startswith("FCA_ 200ul")]
    # W14 (12 N wells in 6 plate columns: 2, 2, 2, 1 + 1, 3, 1) and W15 (3, 3, 3, 2 + 1)
    assert k1000 == [2, 2, 2, 1, 1, 3, 1, 3, 3, 3, 2, 1]
    # six single tips (W03, W09 x2, W11, W13 x2), then the W16 mixes: L1 2 + 1, L2 3, L3 3, L4 1 + 2
    assert k200 == [1, 1, 1, 1, 1, 1, 2, 1, 3, 3, 1, 2]


def test_wells_by_column():
    wells = ["C1", "E1", "C5", "E5", "C9", "B10", "D10", "F10", "H11", "E9"]
    assert wells_by_column(wells) == [["C1", "E1"], ["C5", "E5"], ["C9", "E9"], ["B10", "D10", "F10"], ["H11"]]


def _step(tmp_path, inst):
    inst.run_open, inst.run_started = True, "run-1"
    Mission(tmp_path).write({"mission_id": "m", "run_started": "run-1"})
    return Step(FakeClient(inst), {"mission_dir": str(tmp_path)}, settle=lambda i, label, t: i.get_responses())


def test_a_column_with_two_tips_left_is_split_2_plus_1(tmp_path):
    inst = FakeInstrument(tips={"R": "G3"})
    tips = {"tip_type": "FCA, 1000ul SBS", "rack": "R", "set_next_tip": False}
    Pipetting(_step(tmp_path, inst)).transfer_multi(tips, "T", "A1", 50.0, "P", ["B10", "D10", "F10"], "Multi")
    calls = [(c, a) for c, a in inst.sila_calls() if c in ("LiquidHandling.GetTips", "LiquidHandling.Dispense")]
    assert calls == [
        ("LiquidHandling.GetTips", ("FCA, 1000ul SBS", [1, 2], "R")),
        ("LiquidHandling.Dispense", ("P", ["B10", "D10"], [50.0, 50.0], "Multi", [1, 2])),
        ("LiquidHandling.GetTips", ("FCA, 1000ul SBS", [1], "R")),
        ("LiquidHandling.Dispense", ("P", ["F10"], [50.0], "Multi", [1])),
    ]
    assert inst.next_well("R") == "B4"


def test_temperature_is_polled_until_reached(tmp_path, no_real_waits):
    inst = FakeInstrument(temperatures=[30.0, 38.5, 41.6])
    value = _step(tmp_path, inst).wait_temperature("BioShake", "ReadTemperature", 41.5, 30.0, 1800.0)
    assert value == 41.6
    assert [c for c, _ in inst.sila_calls()] == ["BioShake.ReadTemperature"] * 3
    assert no_real_waits == [30.0, 30.0]


def test_temperature_not_reached_fails(tmp_path, monkeypatch):
    inst = FakeInstrument(temperatures=[30.0])
    clock = iter(range(0, 10_000, 100))
    monkeypatch.setattr(steps_module.time, "monotonic", lambda: next(clock))
    with pytest.raises(MissionError, match="below 41.5"):
        _step(tmp_path, inst).wait_temperature("BioShake", "ReadTemperature", 41.5, 30.0, 1800.0)


@pytest.mark.parametrize(
    "failing",
    [
        ("LiquidHandling.Aspirate", ("4 Well SBS Trough[001]", ["A2"] * 3, [196.0] * 3, "Water Free Multi", [1, 2, 3])),
        ("BioShake.LockPlate", ()),
        ("PlateHandling.MeasureWorktablePlate", ("96 Well Flat_Custom[001]", "OFML_Abs405.mth")),
    ],
)
def test_a_failure_stops_everything_and_ends_the_run(tmp_path, config, failing):
    def fail(feature, command, args):
        if (f"{feature}.{command}", args) == failing:
            return "Active Stop"
        return already_registered(feature, command, args)

    inst = instrument(fail=fail)
    code, mission, _ = run(tmp_path, config, inst)

    first = EXPECTED.index(failing)
    assert code == 1
    assert inst.sila_calls() == [*EXPECTED[: first + 1], END]  # no DropTips, no retry: only EndRun after it
    assert mission.state()["state"] == m.RUN_ENDED and not inst.run_open


def test_abs405_without_result_file_is_a_failure(tmp_path, config):
    inst = instrument(missing_results={"Abs600.mth", "OFML_Abs405.mth"})
    code, mission, _ = run(tmp_path, config, inst)
    assert code == 1 and mission.state()["state"] == m.RUN_ENDED
