"""Checks the backend before a run starts, with a stand-in for the UniteLabs FluentControl connector."""

import pytest

from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError, FluentBackendConfig, FluentOdtcBackend


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
    backend = FluentOdtcBackend(FluentBackendConfig())
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
