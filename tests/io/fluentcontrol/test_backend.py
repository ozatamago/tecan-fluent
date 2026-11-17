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


class _TrackedProperty:
    def __init__(self, getter):
        self.getter = getter

    def get(self):
        return self.getter()


def _channel_backend(state, name="ofml", alive=True):
    from types import SimpleNamespace

    touched = []

    def read(key, value):
        touched.append(key)
        return value

    client = SimpleNamespace(
        ExecutionChannelController=SimpleNamespace(
            Channel=_TrackedProperty(lambda: read("channel", name)),
            IsAlive=_TrackedProperty(lambda: read("alive", alive)),
        )
    )
    backend = FluentControlBackend(FluentBackendConfig())
    backend._client = client
    backend._state = lambda: state
    return backend, touched


@pytest.mark.parametrize("state", ["EditMode", "RunModePreparingRun", "RunModeWaitingForSystem", "RunModeBeginRun"])
def test_initializing_run_does_not_touch_stale_alive_channel(state):
    backend, touched = _channel_backend(state)
    assert not backend._our_channel_open()
    assert touched == []


@pytest.mark.parametrize("name,alive,expected", [("ofml", True, True), ("main", True, False), ("ofml", False, False)])
def test_running_requires_matching_alive_channel(name, alive, expected):
    backend, _ = _channel_backend("RunModeRunning", name, alive)
    assert backend._our_channel_open() is expected


def test_open_run_waits_for_running_before_inspecting_channel(monkeypatch):
    from types import SimpleNamespace

    state = {"native": "EditMode", "prepared": False, "started": False, "sleeps": 0}
    channel_reads = []

    def prepare(_method):
        state.update(native="RunModePreparingRun", prepared=True)

    def run():
        state.update(native="RunModeWaitingForSystem", started=True)

    def read_channel():
        assert state["native"] == "RunModeRunning"
        channel_reads.append(state["native"])
        return "ofml"

    def advance(_seconds):
        state["sleeps"] += 1
        state["native"] = "RunModeRunning"

    client = SimpleNamespace(
        FluentController=SimpleNamespace(IsAttached=_TrackedProperty(lambda: True)),
        RuntimeController=SimpleNamespace(
            State=_TrackedProperty(lambda: state["native"]), PrepareMethod=prepare, RunMethod=run
        ),
        RunController=SimpleNamespace(ActiveDialogs=_TrackedProperty(list)),
        ExecutionChannelController=SimpleNamespace(
            Channel=_TrackedProperty(read_channel), IsAlive=_TrackedProperty(lambda: True)
        ),
    )
    backend = FluentControlBackend(FluentBackendConfig())
    backend._client = client
    monkeypatch.setattr("unitelabs.tecan_fluent.io.fluentcontrol.backend.time.sleep", advance)
    backend._open_run(lambda _: None)
    assert state["prepared"] and state["started"] and state["sleeps"] == 1
    assert channel_reads == ["RunModeRunning"]
