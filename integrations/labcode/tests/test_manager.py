"""The run manager and the environment scripts with an in-process fake SiLA2 client (fast; no lc run).

The workflow is executed by a stand-in for lc run (fakes.run_in_process) that runs the environment's scripts in
the workflow's dependency order; test_lc_run.py does the same through the real lc run.
"""

from __future__ import annotations

import pytest
from fluent780_labcode import mission as m
from fluent780_labcode import steps as steps_module
from fluent780_labcode.manager import RunManager

from conftest import ADD_LIDS, BOUNDARY, END, ENV, HOLD, SILA_CALLS, START, STEPS, WORKFLOW, steps_from_events
from fakes import FakeClient, FakeInstrument, run_in_process


@pytest.fixture(autouse=True)
def no_real_waits(monkeypatch):
    waits = []
    monkeypatch.setattr(steps_module.time, "sleep", lambda s: waits.append(s))
    return waits


def run(tmp_path, config, instrument, **kw):
    clients = []

    def connect(host, port, insecure=False):
        assert (host, port) == ("10.5.1.156", 50060)  # the environment's address; nothing is reached
        clients.append(FakeClient(instrument))
        return clients[-1]

    def labcode(mission, cfg):
        return run_in_process(mission.directory, connect("10.5.1.156", 50060))

    def settle(instance, label, timeout):
        return instance.get_responses()

    manager = RunManager({**config, **kw}, connect=connect, settle=settle, run_labcode=labcode)
    mission = manager.prepare(WORKFLOW, ENV, BOUNDARY, tmp_path / "mission", None)
    code = manager.run(mission)
    return code, mission, clients


def test_all_22_steps_in_order_inside_one_run(tmp_path, config, no_real_waits):
    instrument = FakeInstrument()
    code, mission, clients = run(tmp_path, config, instrument)

    assert code == 0
    assert instrument.sila_calls() == SILA_CALLS
    assert steps_from_events(mission.events()) == [*ADD_LIDS, *STEPS]
    assert no_real_waits == [10.0]
    assert not instrument.run_open
    assert mission.state()["state"] == m.COMPLETED
    assert mission.data["run_started"] and all(c.closed for c in clients[:1])


@pytest.mark.parametrize("failing_step", [1, 7, 12, 21])
def test_a_failure_stops_the_workflow_and_ends_the_run(tmp_path, config, failing_step):
    failing = STEPS[failing_step - 1]
    instrument = FakeInstrument(fail=lambda f, c, a: "Active Stop" if (f"{f}.{c}", a) == failing else None)
    code, mission, _ = run(tmp_path, config, instrument)

    sent = [s for s in STEPS[:failing_step] if s is not HOLD]
    assert code == 1
    assert instrument.sila_calls() == [START, *ADD_LIDS, *sent, END]  # nothing after the failure but EndRun
    assert not instrument.run_open
    state = mission.state()
    assert state["state"] == m.RUN_ENDED and "labcode did not complete" in state["failure"]
    failed = [e for e in mission.events() if e["kind"] == "failed"]
    assert len(failed) == 1 and "Active Stop" in failed[0]["error"]


def test_hold_policy_leaves_the_run_open(tmp_path, config):
    failing = STEPS[6]
    instrument = FakeInstrument(fail=lambda f, c, a: "Active Stop" if (f"{f}.{c}", a) == failing else None)
    code, mission, _ = run(tmp_path, config, instrument, on_failure="hold")

    assert code == 1
    assert instrument.sila_calls()[-1] == failing
    assert END not in instrument.sila_calls()
    assert instrument.run_open
    assert mission.state()["state"] == m.UNCERTAIN and mission.state()["run_left_open"]


def test_an_open_run_is_never_joined(tmp_path, config):
    instrument = FakeInstrument(run_open=True)
    code, mission, _ = run(tmp_path, config, instrument)

    assert code == 1
    assert instrument.sila_calls() == []  # no StartRun, no EndRun of someone else's run
    assert mission.state()["state"] == "REFUSED"


def test_a_lost_run_is_neither_restarted_nor_ended(tmp_path, config):
    instrument = FakeInstrument()

    def lose_run(feature, command, args):
        if (f"{feature}.{command}", args) == STEPS[2]:
            instrument.run_open, instrument.run_started = True, "someone-else"  # e.g. FluentControl restarted
        return None

    instrument.fail = lose_run
    code, mission, _ = run(tmp_path, config, instrument)

    assert code == 1
    assert instrument.sila_calls() == [START, *ADD_LIDS, *STEPS[:3]]  # step 4 was refused before sending
    assert mission.state()["state"] == m.UNCERTAIN
    assert any(e["kind"] == "run_mismatch" for e in mission.events())


def test_add_lid_keeps_a_lid_that_is_already_registered(tmp_path, config):
    instrument = FakeInstrument(fail=lambda f, c, a: "PlateB_Lid[001] already exists" if a[:1] == ("PlateB_Lid[001]",)
                                and c == "AddLabware" else None)  # fmt: skip
    code, mission, _ = run(tmp_path, config, instrument)

    assert code == 0
    assert any(e["kind"] == "kept" for e in mission.events())


def test_unknown_cover_site_fails_before_sending(tmp_path, config):
    config["cover_sites"] = {"static": {}}
    instrument = FakeInstrument()
    code, mission, _ = run(tmp_path, config, instrument)

    assert code == 1
    assert instrument.sila_calls() == [START, END]
    assert mission.state()["state"] == m.RUN_ENDED
