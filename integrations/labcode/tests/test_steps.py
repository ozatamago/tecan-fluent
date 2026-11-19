"""fluent780_labcode.steps and cover_sites on their own."""

from __future__ import annotations

import math
from collections import namedtuple

import pytest
from fluent780_labcode.cover_sites import CoverSites
from fluent780_labcode.mission import Mission, MissionError
from fluent780_labcode.steps import Step, absorbance_reading

from fakes import FakeClient, FakeInstrument


def mission_with_run(tmp_path, instrument, **extra):
    instrument.run_open, instrument.run_started = True, "run-1"
    mission = Mission(tmp_path)
    mission.write({"mission_id": "m1", "run_started": "run-1", **extra})
    return {"mission_dir": str(tmp_path)}


def test_a_step_without_a_mission_is_refused(tmp_path):
    with pytest.raises(MissionError, match="run manager"):
        Step(FakeClient(FakeInstrument()), {"mission_dir": str(tmp_path)})


def test_nothing_is_sent_when_the_run_is_not_the_missions(tmp_path):
    instrument = FakeInstrument()
    cell = mission_with_run(tmp_path, instrument)
    instrument.run_started = "another-run"
    with pytest.raises(MissionError, match="not open any more"):
        Step(FakeClient(instrument), cell).call("Incubator1", "CloseDoor")
    assert instrument.sila_calls() == []


def test_a_command_is_recorded_before_and_after(tmp_path):
    instrument = FakeInstrument()
    cell = mission_with_run(tmp_path, instrument)
    Step(FakeClient(instrument), cell).call("Incubator1", "StartShaker", 5.0, label="shake")
    kinds = [e["kind"] for e in Mission(tmp_path).events()]
    assert kinds == ["sending", "completed"]
    assert all(e["mission_id"] == "m1" for e in Mission(tmp_path).events())


def test_cover_site_is_resolved_through_the_fluentcontrol_connector(tmp_path):
    asked = []

    class Runtime:
        def ResolveExpression(self, expression):  # noqa: N802 - SiLA2 command name
            asked.append(expression)
            return namedtuple("R", "Result")("2")

    class Connector:
        RuntimeController = Runtime()

    sites = CoverSites({"resolve": {"host": "127.0.0.1", "port": 1234}}, connect=lambda *a, **k: Connector())
    assert sites.index("96 Well Flat_Custom[002]") == 2
    assert asked == ['GetCoverSiteIndex("96 Well Flat_Custom[002]")']
    assert CoverSites({"static": {"X": 5}, "resolve": {"port": 1}}).index("X") == 5
    with pytest.raises(MissionError, match="not known"):
        CoverSites({}).index("X")


def test_absorbance_reading_from_the_connectors_structure():
    Well = namedtuple("WellValue_Struct", "Label Well Value")
    Result = namedtuple("MeasurementResult_Struct", "Method Labels Values ResultFile Metadata")
    responses = namedtuple("MeasureWorktablePlate_Responses", "Result")(
        Result(
            "OFML_Abs405.mth",
            ["Label1"],
            [Well("Label1", "A1", 0.0524), Well("Label1", "A2", math.nan)],
            r"C:\x.asc",
            [],
        )
    )
    assert absorbance_reading(responses) == {
        "method": "OFML_Abs405.mth", "result_file": r"C:\x.asc",
        "labels": ["Label1"], "wells": ["A1"], "values": [0.0524], "note": "",
    }  # fmt: skip
