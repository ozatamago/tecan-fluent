"""The 22 steps of realrun_20261119.py (passed on the real Fluent 780, 2026-11-19 15:05-15:15) as data."""

from __future__ import annotations

from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
WORKFLOWS = HERE.parent / "workflows"
WORKFLOW = WORKFLOWS / "colour_water_layout.workflow.yaml"
ENV = WORKFLOWS / "colour_water_layout.env.yaml"
BOUNDARY = WORKFLOWS / "colour_water_layout.boundary.yaml"
DOCUMENT = WORKFLOWS / "colour_water_layout.document.yaml"

A, B, TR = "96 Well Flat_Custom[002]", "96 Well Flat_Custom[001]", "4 Well SBS Trough[001]"
R50, R200 = "FCA_ 50ul SBS[001]", "FCA_ 200ul SBS[003]"

# Cover-site indices for the tests only. The real values come from GetCoverSiteIndex on the instrument.
COVER = {A: 12, B: 11, TR: 13, R50: 15, R200: 17}


def gcn(holder: str) -> str:
    return f'GetCoverSiteName("{holder}")'


ADD_LIDS = [
    ("Labware.AddLabware", ("PlateA_Lid[001]", "Lid_9mm_Custom", gcn(A), COVER[A])),
    ("Labware.AddLabware", ("PlateB_Lid[001]", "Lid_9mm_Custom", gcn(B), COVER[B])),
    ("Labware.AddLabware", ("TroughLid[001]", "Lid_9mm", gcn(TR), COVER[TR])),
    ("Labware.AddLabware", ("Rack50_Lid[001]", "Lid_DiTiFCA", gcn(R50), COVER[R50])),
    ("Labware.AddLabware", ("Rack200_Lid[001]", "Lid_DiTiFCA", gcn(R200), COVER[R200])),
]

# Step n of the script is STEPS[n - 1]. Step 19 is the 10 s wait (time.sleep(10) in the script).
HOLD = ("hold", (10.0,))
STEPS = [
    ("Labware.TransferLabware", ("PlateA_Lid[001]", "HotelMP_Pos", 2)),
    ("Labware.TransferLabware", ("Rack50_Lid[001]", "Nest7mm_Pos", 3)),
    ("Labware.TransferLabware", ("Rack200_Lid[001]", "Nest7mm_Pos", 7)),
    ("Labware.TransferLabware", ("PlateA_Lid[001]", gcn(A), COVER[A])),
    ("Labware.TransferLabware", (A, "BioShake_Q1_Adapter_Site", 1)),
    ("Labware.TransferLabware", (A, "CPLC_Flat_Pos", 3)),
    ("Labware.TransferLabware", ("PlateB_Lid[001]", "HotelMP_Pos", 3)),
    ("Labware.TransferLabware", ("TroughLid[001]", "HotelMP_Pos", 4)),
    ("Labware.TransferLabware", ("TroughLid[001]", gcn(TR), COVER[TR])),
    ("Labware.TransferLabware", ("Rack200_Lid[001]", gcn(R200), COVER[R200])),
    ("Labware.TransferLabware", ("Rack50_Lid[001]", gcn(R50), COVER[R50])),
    ("PlateHandling.MeasureWorktablePlate", (B, "OFML_Abs405.mth")),
    ("Labware.TransferLabware", ("PlateB_Lid[001]", gcn(B), COVER[B])),
    ("Incubator1.SetTemperature", (37.0,)),
    ("PlateTransfer.MoveLabware", (B, "Regrip_Pos", 1)),
    ("PlateTransfer.MoveLabware", (B, "Incub6Shake_Pos", 1)),
    ("Incubator1.CloseDoor", ()),
    ("Incubator1.StartShaker", (5.0,)),
    HOLD,
    ("Incubator1.StopShaker", ()),
    ("PlateTransfer.MoveLabware", (B, "Nest7mm_Pos", 1)),
    ("Incubator1.CloseDoor", ()),
]
assert len(STEPS) == 22

START, END = ("RunControl.StartRun", ()), ("RunControl.EndRun", ())
# what the instrument receives when everything succeeds (the wait is not a command)
SILA_CALLS = [START, *ADD_LIDS, *[s for s in STEPS if s is not HOLD], END]


def steps_from_events(events: list[dict]) -> list[tuple[str, tuple]]:
    """The commands and waits the operations recorded in events.jsonl, in order (StartRun/EndRun excluded)."""
    out = []
    for e in events:
        if e["kind"] == "sending" and e.get("feature") != "RunControl":
            out.append((f"{e['feature']}.{e['command']}", tuple(e["args"])))
        elif e["kind"] == "hold":
            out.append(("hold", (float(e["seconds"]),)))
    return out


@pytest.fixture
def config():
    return {"cover_sites": {"static": dict(COVER)}, "seconds_per_tick": 0.2, "first_plan_max_time": 10}
