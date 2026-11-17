"""Exercise patched lower-connector methods with inert fakes and no COM or network."""

import ast
import contextlib
import enum
import sys
import unittest
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

if len(sys.argv) < 2:
    raise SystemExit("Usage: python test_channel_cache.py /path/to/fluentcontrol_protocol.py")
SOURCE = Path(sys.argv.pop(1))


class State(enum.IntEnum):
    EditMode = 6
    RunModePreparingRun = 8
    RunModePreparingRecovery = 9
    RunModeRunning = 12
    RunModeRunFinished = 16


class InvalidState(Exception):
    def __init__(self, description):
        super().__init__(description)


class ComError(Exception):
    pass


def extract_class(path, class_name, method_names, namespace):
    tree = ast.parse(path.read_text())
    source = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    selected = [
        node
        for node in source.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in method_names
    ]
    assert {node.name for node in selected} == set(method_names)
    cls = ast.ClassDef(name="Candidate", bases=[], keywords=[], body=selected, decorator_list=[])
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), cls], type_ignores=[]
    )
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace["Candidate"]


class ProtocolCacheTests(unittest.IsolatedAsyncioTestCase):
    def make_protocol(self, state):
        async def timeout(*args, **kwargs):
            raise TimeoutError

        async def ready(predicate, **kwargs):
            self.assertTrue(predicate(State.RunModePreparingRun))

        async def get_state():
            return state

        namespace = {
            "StateMachineStates": State,
            "InvalidState": InvalidState,
            "RuntimeUnavailable": RuntimeError,
            "contextlib": contextlib,
            "pathlib": SimpleNamespace(WindowsPath=PurePosixPath),
            "shutil": SimpleNamespace(rmtree=lambda *a, **k: None),
            "comtypes": SimpleNamespace(COMError=ComError),
            "Errors": SimpleNamespace(InvalidStatePrepareMethod="invalid", UnknownMethodName="unknown"),
        }
        cls = extract_class(
            SOURCE,
            "FluentControlProtocol",
            {"prepare_method", "_on_state_changed", "_on_channel_opens", "execution_channel"},
            namespace,
        )
        protocol = cls()
        protocol.get_state = get_state
        protocol.logger = SimpleNamespace(info=lambda *a: None)
        protocol.states = SimpleNamespace(wait_for=ready, update=lambda value: None)
        protocol.errors = SimpleNamespace(wait_for=timeout)
        protocol._execution_channels = ["stale-proxy"]

        def prepare(name):
            self.assertEqual(protocol._execution_channels, [])

        protocol.runtime = SimpleNamespace(PrepareMethod=prepare)
        return protocol

    async def test_idle_prepare_discards_proxy_before_native_prepare_and_needs_new_callback(self):
        protocol = self.make_protocol(State.EditMode)
        await protocol.prepare_method("OFML_ApiHost")
        self.assertIsNone(protocol.execution_channel)
        protocol._on_channel_opens("fresh-proxy")
        self.assertEqual(protocol.execution_channel, "fresh-proxy")

    async def test_active_run_prepare_is_refused_without_discarding_its_channel(self):
        protocol = self.make_protocol(State.RunModeRunning)
        with self.assertRaises(InvalidState):
            await protocol.prepare_method("OFML_ApiHost")
        self.assertEqual(protocol.execution_channel, "stale-proxy")

    async def test_missing_close_event_is_repaired_on_idle_transition(self):
        for idle in [State.EditMode, State.RunModeRunFinished]:
            protocol = self.make_protocol(State.RunModeRunning)
            protocol._on_state_changed(State.RunModeRunning, idle)
            self.assertIsNone(protocol.execution_channel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
