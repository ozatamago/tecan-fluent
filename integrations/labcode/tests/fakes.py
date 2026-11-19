"""Test doubles: an in-process fake SiLA2 client, a loopback fake SiLA2 server, and an in-process stand-in for
``lc run`` that executes the environment scripts in workflow order. None of them reaches an instrument."""

from __future__ import annotations

import json
import socket
import threading
import uuid
from collections import namedtuple
from pathlib import Path
from typing import Any

import yaml

# -- the fake instrument (shared by the client and the server) ---------------------------------------------------------

# Commands of the Tecan Fluent connector used by the workflow: parameters and the response (name, SiLA type).
COMMANDS: dict[str, dict[str, Any]] = {
    "RunControl": {
        "StartRun": ([], ("RecordFolder", "String")),
        "EndRun": ([], ("Commands", "Integer")),
    },
    "Labware": {
        "AddLabware": ([("Label", "String"), ("LabwareType", "String"), ("Location", "String"), ("Site", "Integer")],
                       None),
        "TransferLabware": ([("Labware", "String"), ("Location", "String"), ("Site", "Integer")], None),
    },
    "PlateTransfer": {
        "MoveLabware": ([("Labware", "String"), ("Location", "String"), ("Site", "Integer")],
                        ("NewPosition", "String")),
    },
    "PlateHandling": {
        "MeasureWorktablePlate": ([("Labware", "String"), ("Method", "String")], ("Result", "String")),
    },
    "Incubator1": {
        "SetTemperature": ([("Temperature", "Real")], None),
        "CloseDoor": ([], None),
        "StartShaker": ([("Frequency", "Real")], None),
        "StopShaker": ([], None),
    },
}  # fmt: skip
PROPERTIES = {"RunControl": {"RunOpen": "Boolean", "RunStarted": "String"}}


class FakeInstrument:
    """The state a Tecan Fluent connector keeps across connections: the open run and the commands received.

    `fail` is a predicate ``(feature, command, args) -> str | None``: a message makes that command fail."""

    def __init__(self, fail=None, run_open: bool = False):
        self.fail = fail
        self.run_open = run_open
        self.run_started = "already-open" if run_open else ""
        self.calls: list[tuple[str, tuple]] = []
        self.lock = threading.Lock()

    def execute(self, feature: str, command: str, args: tuple) -> Any:
        with self.lock:
            self.calls.append((f"{feature}.{command}", tuple(args)))
            message = self.fail(feature, command, tuple(args)) if self.fail else None
            if message:
                raise RuntimeError(message)
            if (feature, command) == ("RunControl", "StartRun"):
                if self.run_open:
                    raise RuntimeError("a run is already open")
                self.run_open, self.run_started = True, uuid.uuid4().hex
                return r"C:\records\fake"
            if (feature, command) == ("RunControl", "EndRun"):
                if not self.run_open:
                    raise RuntimeError("no run is open")
                self.run_open = False
                return len(self.calls)
            if not self.run_open:
                raise RuntimeError("no run is open")
            if command == "MoveLabware":
                return f"{args[1]}[{args[2]}]"
            if command == "MeasureWorktablePlate":
                values = [{"Label": "Label1", "Well": w, "Value": 0.05} for w in ("A1", "A2")]
                return json.dumps({"Method": args[1], "Labels": ["Label1"], "Values": values, "ResultFile": "fake.asc"})
            return None

    def prop(self, feature: str, name: str) -> Any:
        return {"RunOpen": self.run_open, "RunStarted": self.run_started}[name]

    def sila_calls(self) -> list[tuple[str, tuple]]:
        return list(self.calls)


# -- in-process client -----------------------------------------------------------------------------------------------


class _Instance:
    done = True

    def __init__(self, fn):
        self._fn = fn

    def get_responses(self):
        return self._fn()


class _Property:
    def __init__(self, get):
        self.get = get


class _Feature:
    def __init__(self, instrument: FakeInstrument, name: str):
        self._instrument, self._name = instrument, name

    def __getattr__(self, attr: str):
        if attr in PROPERTIES.get(self._name, {}):
            return _Property(lambda: self._instrument.prop(self._name, attr))
        spec = COMMANDS[self._name][attr]

        def command(*args):
            # Executed when the command is issued; a failure surfaces from get_responses, as in sila2.
            try:
                value, error = self._instrument.execute(self._name, attr, args), None
            except RuntimeError as exc:
                value, error = None, exc

            def responses():
                if error:
                    raise error
                return namedtuple("Responses", [spec[1][0]])(value) if spec[1] else namedtuple("Responses", [])()

            return _Instance(responses)

        return command


class FakeClient:
    """Stands in for ``sila2.client.SilaClient`` connected to the Tecan Fluent connector."""

    def __init__(self, instrument: FakeInstrument):
        self.instrument = instrument
        self.closed = False

    def __getattr__(self, name: str):
        if name in COMMANDS or name in PROPERTIES:
            return _Feature(self.instrument, name)
        raise AttributeError(name)

    def close(self):
        self.closed = True


# -- loopback SiLA2 server -------------------------------------------------------------------------------------------


def _type(t: str) -> str:
    return f"<Basic>{t}</Basic>"


def _el(tag: str, name: str, t: str) -> str:
    return (
        f"<{tag}><Identifier>{name}</Identifier><DisplayName>{name}</DisplayName><Description>Fake.</Description>"
        f"<DataType>{_type(t)}</DataType></{tag}>"
    )


class FakeServer:
    """A loopback-only SiLA2 server with the commands of COMMANDS, backed by a FakeInstrument."""

    def __init__(self, instrument: FakeInstrument):
        self.instrument = instrument
        self.server = None
        self.port = 0

    def start(self) -> int:
        from sila2.framework import Feature
        from sila2.server import FeatureImplementationBase, SilaServer

        server = SilaServer("Fake Fluent", "Fake", "Loopback test server; never reaches hardware", "0.1.0",
                            "https://example.invalid", max_grpc_workers=20, max_child_task_workers=10)  # fmt: skip
        for feature, commands in COMMANDS.items():
            parts = [
                '<Feature xmlns="http://www.sila-standard.org" SiLA2Version="1.0" FeatureVersion="1.0" '
                'Originator="org.example" Category="test">',
                f"<Identifier>{feature}</Identifier><DisplayName>{feature}</DisplayName><Description>Fake.</Description>",
            ]
            impl = FeatureImplementationBase(server)
            for command, (params, response) in commands.items():
                parts.append(
                    f"<Command><Identifier>{command}</Identifier><DisplayName>{command}</DisplayName>"
                    "<Description>Fake.</Description><Observable>Yes</Observable>"
                )
                parts += [_el("Parameter", n, t) for n, t in params]
                if response:
                    parts.append(_el("Response", *response))
                parts.append("</Command>")

                def make(f=feature, c=command, resp=response):
                    def call(*args, metadata=None, instance=None):
                        value = self.instrument.execute(f, c, args)
                        return namedtuple("Response", [resp[0]])(value) if resp else None

                    return call

                setattr(impl, command, make())
            for prop, t in PROPERTIES.get(feature, {}).items():
                parts.append(
                    f"<Property><Identifier>{prop}</Identifier><DisplayName>{prop}</DisplayName>"
                    f"<Description>Fake.</Description><Observable>No</Observable><DataType>{_type(t)}</DataType>"
                    "</Property>"
                )
                setattr(impl, f"get_{prop}", lambda metadata=None, f=feature, n=prop: self.instrument.prop(f, n))
            parts.append("</Feature>")
            server.set_feature_implementation(Feature("".join(parts)), impl)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        server.start_insecure("127.0.0.1", self.port, enable_discovery=False)
        self.server = server
        return self.port

    def stop(self):
        if self.server:
            self.server.stop(grace_period=0)


# -- in-process stand-in for lc run ----------------------------------------------------------------------------------


def _function(code: str, params: list[str]):
    body = "\n".join("    " + line for line in code.splitlines()) or "    pass"
    namespace: dict = {}
    exec(f"def __op({', '.join(params)}, sila2_client=None, sila2_clients=None):\n{body}\n", namespace)  # noqa: S102
    return namespace["__op"]


def _order(nodes: list[dict]) -> list[dict]:
    """Nodes in dependency order (Kahn's algorithm, ties in document order)."""
    done: set[str] = set()
    out: list[dict] = []
    pending = list(nodes)
    while pending:
        for node in pending:
            sources = [
                b["from"].split(".")[0]
                for section in ("state", "bind")
                for b in (node.get(section) or {}).values()
                if "from" in b
            ]
            if all(s == "inputs" or s in done for s in sources):
                out.append(node)
                done.add(node["id"])
                pending.remove(node)
                break
        else:
            raise ValueError("cycle")
    return out


def run_in_process(directory: Path, client: FakeClient) -> int:
    """Execute the mission's workflow like ``lc run`` would, but in this process and with `client` as the
    ``sila2_client`` of every operation. Returns 0 on success, 1 when an operation failed (as ``lc run``)."""
    wf = yaml.safe_load((directory / "workflow.yaml").read_text())
    env = yaml.safe_load((directory / "environment.yaml").read_text())
    bnd = yaml.safe_load((directory / "boundary.yaml").read_text())["boundary"]
    procs = wf["processes"]

    def execute(name: str, inputs: dict) -> dict:
        proc = procs[name]
        if proc["kind"] == "atomic":
            code = env["processes"][name]["modes"][0]["x-labcode"]["script"]["code"]
            result = _function(code, list(proc["inputs"]))(**inputs, sila2_client=client, sila2_clients={})
            for out, src in ((proc.get("objects") or {}).get("map") or {}).items():
                result.setdefault(out.split(".", 1)[1], inputs[src.split(".", 1)[1]])
            return result
        values: dict[str, dict] = {}

        def source(b: dict) -> Any:
            if "value" in b:
                return b["value"]
            head, port = b["from"].split(".", 1)
            return inputs[port] if head == "inputs" else values[head][port]

        for node in _order(proc["body"]["nodes"]):
            args = {k: source(b) for sec in ("state", "bind") for k, b in (node.get(sec) or {}).items()}
            values[node["id"]] = execute(node["process"], args)
        return {k: source(b) for k, b in proc["body"]["returns"].items()}

    try:
        execute(wf.get("entry", "main"), {k: v.get("view") for k, v in bnd["inputs"].items()})
    except Exception:
        return 1
    # what lc run -o writes, reduced to what the run manager reads
    (directory / "status.yaml").write_text(yaml.safe_dump({"activities": [{"status": "completed"}]}))
    return 0
