"""Checks the backend before a run starts, with a stand-in for the UniteLabs FluentControl connector."""

import pytest

from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError, FluentBackendConfig, FluentControlBackend


class _FakeClient:
    """Just enough of the UniteLabs FluentControl connector for the checks before a run starts."""

    def __init__(self, state, dialogs):
        def prop(v):
            return type("P", (), {"get": lambda self: v})()

        dlg = [type("D", (), {"DialogIdentifier": i, "Description": t})() for i, t in dialogs]
        self.FluentController = type("F", (), {"IsAttached": prop(True)})()
        self.RuntimeController = type("R", (), {"State": prop(state), "PrepareMethod": self._prepare})()
        self.RunController = type("C", (), {"ActiveDialogs": prop(dlg)})()
        self.prepared = False

    def _prepare(self, *_a):
        self.prepared = True
        raise RuntimeError("stop here")


def _open_run_with(state, dialogs):
    backend = FluentControlBackend(FluentBackendConfig())
    client = _FakeClient(state, dialogs)
    backend._client = client
    with pytest.raises(Exception) as caught:
        backend._open_run(lambda _: None)
    return client, caught.value


def test_open_dialog_after_a_stopped_run_refuses_before_prepare_method():
    # 2026-10-20: RunModeRunFinished with "a door was opened" still open; PrepareMethod hung for 2 minutes
    client, exc = _open_run_with(
        "RunModeRunFinished",
        [("Unused ID", ""), ("VX_RUNTM_002_016", "The run was stopped because a door was opened.")],
    )
    assert isinstance(exc, BackendError) and "door was opened" in str(exc)
    assert not client.prepared


def test_empty_unused_id_dialog_does_not_block():
    client, _ = _open_run_with("EditMode", [("Unused ID", "")])
    assert client.prepared


def test_open_run_notes_when_the_run_was_started():
    from unitelabs.tecan_fluent.io.fluentcontrol.backend import _dotnet_ticks_now

    before = _dotnet_ticks_now()
    # the start is noted before PrepareMethod, a little early, so a worktable written for the run is not missed
    backend = FluentControlBackend(FluentBackendConfig())
    backend._client = _FakeClient("EditMode", [])
    with pytest.raises(RuntimeError):
        backend._open_run(lambda _: None)
    assert before - 31 * 10_000_000 < backend._run_opened_ticks <= _dotnet_ticks_now()


def test_removal_of_labware_absent_from_the_runs_worktable_is_not_sent():
    # 2026-11-18: after an aborted run FluentControl started from its recovery state, which no longer had the tip
    # rack FCA_ 10ul SBS[003]; its RemoveLabware failed with "does not exist" and ended the run
    from unitelabs.tecan_fluent.io.fluent.gripper.statements import add_labware_xml, remove_labware_xml

    backend = FluentControlBackend(FluentBackendConfig())
    backend._run_opened_ticks = 123
    asked = []

    def run_base_labels(since):
        asked.append(since)
        return {"Trough[001]", "Rack[002]"}

    backend.preflight.run_base_labels = run_base_labels
    steps = [
        ("RemoveLabware Trough[001]", remove_labware_xml("Trough[001]")),
        ("RemoveLabware Rack[002]", remove_labware_xml("Rack[002]")),
        ("RemoveLabware Rack[003]", remove_labware_xml("Rack[003]")),
        ("AddLabware Rack[002]", add_labware_xml("FCA, 10ul SBS", "Rack[002]", "Nest61mm_Pos_1", 5)),
    ]
    info = {}
    kept = backend._without_absent_removals(steps, info)
    assert asked == [123]
    assert [label for label, _ in kept] == [
        "RemoveLabware Trough[001]",
        "RemoveLabware Rack[002]",
        "AddLabware Rack[002]",
    ]
    assert info["already_absent"] == ["Rack[003]"]
    # the worktable of the run is not known: everything is sent
    backend.preflight.run_base_labels = lambda since: None
    assert backend._without_absent_removals(steps, {}) == steps
