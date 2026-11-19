"""lc run itself, against a loopback fake SiLA2 server (never the instrument).

labcode runs each operation in a child process that connects to the server anew; the fake server keeps the run
across those connections, as the Tecan Fluent connector does. About a minute per run (27 operations, and the 10 s
shake).
"""

from __future__ import annotations

import pytest
import yaml
from fluent780_labcode import mission as m
from fluent780_labcode.manager import RunManager

from conftest import ADD_LIDS, BOUNDARY, END, ENV, HOLD, SILA_CALLS, START, STEPS, WORKFLOW, steps_from_events
from fakes import FakeInstrument, FakeServer

pytestmark = pytest.mark.integration


def lc_run(tmp_path, config, instrument):
    server = FakeServer(instrument)
    port = server.start()
    try:
        manager = RunManager(config)
        mission = manager.prepare(WORKFLOW, ENV, BOUNDARY, tmp_path / "mission", ("127.0.0.1", port))
        return manager.run(mission), mission
    finally:
        server.stop()


def test_lc_run_sends_the_22_steps_in_one_run(tmp_path, config):
    instrument = FakeInstrument()
    code, mission = lc_run(tmp_path, config, instrument)

    log = (mission.directory / "lc_run.log").read_text()
    assert code == 0, log
    assert instrument.sila_calls() == SILA_CALLS
    assert steps_from_events(mission.events()) == [*ADD_LIDS, *STEPS]
    # every operation ran in a process of its own, all inside the one run
    pids = {e["pid"] for e in mission.events() if e["kind"] == "sending" and e["feature"] != "RunControl"}
    assert len(pids) == 26
    assert mission.state()["state"] == m.COMPLETED and not instrument.run_open
    result = yaml.safe_load((mission.directory / "result_boundary.yaml").read_text())
    assert result["boundary"]["outputs"]["reading_b"]["view"]["wells"] == ["A1", "A2"]


def test_lc_run_failure_ends_the_run(tmp_path, config):
    failing = STEPS[6]  # step 7, B's lid to the hotel
    instrument = FakeInstrument(fail=lambda f, c, a: "Active Stop" if (f"{f}.{c}", a) == failing else None)
    code, mission = lc_run(tmp_path, config, instrument)

    sent = [s for s in STEPS[:7] if s is not HOLD]
    assert code == 1
    assert instrument.sila_calls() == [START, *ADD_LIDS, *sent, END]
    assert mission.state()["state"] == m.RUN_ENDED and not instrument.run_open


def test_lc_run_w01_w21_sends_the_commands_of_the_real_run(tmp_path, config):
    from test_colour_water import BOUNDARY as CW_BOUNDARY
    from test_colour_water import EXPECTED as CW_EXPECTED
    from test_colour_water import WORKFLOW as CW_WORKFLOW
    from test_colour_water import instrument

    boundary = yaml.safe_load(CW_BOUNDARY.read_text())
    boundary["boundary"]["inputs"]["wait_scale"]["view"] = 0.001  # 600 s -> 0.6 s
    path = tmp_path / "boundary.yaml"
    path.write_text(yaml.safe_dump(boundary))
    inst = instrument()
    server = FakeServer(inst)
    port = server.start()
    try:
        manager = RunManager(config)
        mission = manager.prepare(CW_WORKFLOW, ENV, path, tmp_path / "mission", ("127.0.0.1", port))
        code = manager.run(mission)
    finally:
        server.stop()

    assert code == 0, (mission.directory / "lc_run.log").read_text()
    assert inst.sila_calls() == CW_EXPECTED
    result = yaml.safe_load((mission.directory / "result_boundary.yaml").read_text())["boundary"]["outputs"]
    assert result["reading_405"]["view"]["wells"] == ["A1", "A2"]
    assert result["reading_600"]["view"]["values"] == [] and "not found" in result["reading_600"]["view"]["note"]
    assert result["shaker_temperature_w07"]["view"] == pytest.approx(42.011)
