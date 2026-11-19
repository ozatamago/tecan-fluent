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

S, INT, R, B, BIN = "String", "Integer", "Real", "Boolean", "Binary"
LS, LI, LR = "List<String>", "List<Integer>", "List<Real>"

# Commands of the Tecan Fluent connector used by the workflows: parameters and responses (name, SiLA type).
COMMANDS: dict[str, dict[str, Any]] = {
    "RunControl": {"StartRun": ([], [("RecordFolder", S)]), "EndRun": ([], [("Commands", INT)])},
    "Labware": {
        "AddLabware": ([("Label", S), ("LabwareType", S), ("Location", S), ("Site", INT)], []),
        "TransferLabware": ([("Labware", S), ("Location", S), ("Site", INT)], []),
    },
    "PlateTransfer": {"MoveLabware": ([("Labware", S), ("Location", S), ("Site", INT)], [("NewPosition", S)])},
    "PlateHandling": {"MeasureWorktablePlate": ([("Labware", S), ("Method", S)], [("Result", S)])},
    "Incubator1": {
        "SetTemperature": ([("Temperature", R)], []),
        "CloseDoor": ([], []),
        "StartShaker": ([("Frequency", R)], []),
        "StopShaker": ([], []),
    },
    "LiquidHandling": {
        "SetNextTipPosition": ([("Rack", S), ("Well", S)], []),
        "GetTips": ([("TipType", S), ("Channels", LI), ("Rack", S)], []),
        "Aspirate": ([("Labware", S), ("Wells", LS), ("Volumes", LR), ("LiquidClass", S), ("Channels", LI)], []),
        "Dispense": ([("Labware", S), ("Wells", LS), ("Volumes", LR), ("LiquidClass", S), ("Channels", LI)], []),
        "Mix": ([("Labware", S), ("Wells", LS), ("Volumes", LR), ("LiquidClass", S), ("Channels", LI),
                 ("Cycles", INT)], []),
        "DropTips": ([("Channels", LI)], []),
    },
    "BioShake": {
        "SetTemperature": ([("Temperature", R)], []),
        "ReadTemperature": ([], [("Reading", S)]),
        "TemperatureOff": ([], []),
        "LockPlate": ([], []),
        "UnlockPlate": ([], []),
    },
    "CoolingHeatingPlates": {"SetTemperature": ([("Slot", INT), ("Temperature", R)], [])},
    "DeckCamera": {"TakeImage": ([("Camera", S)], [("ImagePath", S), ("Preview", BIN)])},
}  # fmt: skip
PROPERTIES = {"RunControl": {"RunOpen": B, "RunStarted": S}, "Deck": {"TipRacks": LS}}

ROWS = "ABCDEFGH"


class FakeInstrument:
    """The state a Tecan Fluent connector keeps across connections: the open run, the next tip of the racks it
    follows, the BioShake temperature, and the commands received.

    `fail` is a predicate ``(feature, command, args) -> str | None``: a message makes that command fail.
    `tips` maps a rack to the well of its next tip; GetTips takes neighbouring tips down the column and refuses
    channels that do not fit in it, as the connector does. `temperatures` are the BioShake readings in turn (the last
    one repeats). `missing_results` are reader methods whose result file is "not found" after measuring."""

    def __init__(self, fail=None, run_open=False, tips=None, temperatures=(42.011,), missing_results=()):
        self.fail = fail
        self.run_open = run_open
        self.run_started = "already-open" if run_open else ""
        self.tips = {rack: (int(w[1:]), ROWS.index(w[0])) for rack, w in (tips or {}).items()}
        self.temperatures = list(temperatures)
        self.missing_results = set(missing_results)
        self.calls: list[tuple[str, tuple]] = []
        self.lock = threading.Lock()

    def next_well(self, rack: str) -> str:
        column, row = self.tips[rack]
        return f"{ROWS[row]}{column}"

    def _take_tips(self, rack: str, k: int) -> None:
        if rack not in self.tips:
            return
        column, row = self.tips[rack]
        if row + k > 8:
            raise RuntimeError(f"{k} channels do not fit in the rest of column {column} of {rack}")
        row += k
        self.tips[rack] = (column + 1, 0) if row == 8 else (column, row)

    def execute(self, feature: str, command: str, args: tuple) -> Any:
        with self.lock:
            args = tuple(list(a) if isinstance(a, list | tuple) else a for a in args)
            self.calls.append((f"{feature}.{command}", args))
            message = self.fail(feature, command, args) if self.fail else None
            if message:
                raise RuntimeError(message)
            if (feature, command) == ("RunControl", "StartRun"):
                if self.run_open:
                    raise RuntimeError("a run is already open")
                self.run_open, self.run_started = True, uuid.uuid4().hex
                return [r"C:\records\fake"]
            if (feature, command) == ("RunControl", "EndRun"):
                if not self.run_open:
                    raise RuntimeError("no run is open")
                self.run_open = False
                return [len(self.calls)]
            if not self.run_open:
                raise RuntimeError("no run is open")
            if command == "SetNextTipPosition" and args[0] in self.tips and args[1] != self.next_well(args[0]):
                raise RuntimeError(f"{args[1]} is not the next tip of {args[0]}")
            if command == "GetTips":
                self._take_tips(args[2], len(args[1]))
            if command == "MoveLabware":
                return [f"{args[1]}[{args[2]}]"]
            if command == "MeasureWorktablePlate":
                if args[1] in self.missing_results:
                    raise RuntimeError(
                        f"ReaderOperationFailed: Result file fake_{args[1]}*.asc not found under C:\\asc"
                    )
                values = [{"Label": "Label1", "Well": w, "Value": 0.05} for w in ("A1", "A2")]
                return [json.dumps({"Method": args[1], "Labels": ["Label1"], "Values": values, "ResultFile": "f.asc"})]
            if command == "ReadTemperature":
                value = self.temperatures.pop(0) if len(self.temperatures) > 1 else self.temperatures[0]
                return [json.dumps({"TemperatureC": value, "LogTimestamp": "", "Source": "fake"})]
            if command == "TakeImage":
                return [r"C:\screen\fake.png", b"jpeg"]
            return []

    def prop(self, feature: str, name: str) -> Any:
        if name == "TipRacks":
            return [f"{rack}: tips (partial since now, next tip {self.next_well(rack)} (set at every run start))"
                    for rack in self.tips]  # fmt: skip
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
        fields = [n for n, _ in COMMANDS[self._name][attr][1]]

        def command(*args):
            # Executed when the command is issued; a failure surfaces from get_responses, as in sila2.
            try:
                value, error = self._instrument.execute(self._name, attr, args), None
            except RuntimeError as exc:
                value, error = None, exc

            def responses():
                if error:
                    raise error
                return namedtuple(f"{attr}_Responses", fields)(*value)

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
    if t.startswith("List<"):
        return f"<List><DataType>{_type(t[5:-1])}</DataType></List>"
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
        for feature in sorted(set(COMMANDS) | set(PROPERTIES)):
            parts = [
                '<Feature xmlns="http://www.sila-standard.org" SiLA2Version="1.0" FeatureVersion="1.0" '
                'Originator="org.example" Category="test">',
                f"<Identifier>{feature}</Identifier><DisplayName>{feature}</DisplayName><Description>Fake.</Description>",
            ]
            impl = FeatureImplementationBase(server)
            for command, (params, responses) in COMMANDS.get(feature, {}).items():
                parts.append(
                    f"<Command><Identifier>{command}</Identifier><DisplayName>{command}</DisplayName>"
                    "<Description>Fake.</Description><Observable>Yes</Observable>"
                )
                parts += [_el("Parameter", n, t) for n, t in params]
                parts += [_el("Response", n, t) for n, t in responses]
                parts.append("</Command>")

                def make(f=feature, c=command, fields=tuple(n for n, _ in responses)):
                    def call(*args, metadata=None, instance=None):
                        value = self.instrument.execute(f, c, args)
                        return namedtuple("Response", fields)(*value) if fields else None

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


def run_mission(directory: Path, config: dict, instrument: FakeInstrument, workflow: Path, env: Path, boundary: Path):
    """Prepare and run a mission with the run manager, the in-process fake client and run_in_process.
    Returns (exit code, mission, the clients the run manager opened)."""
    from fluent780_labcode.manager import RunManager

    clients = []

    def connect(host, port, insecure=False):
        assert (host, port) == ("10.5.1.156", 50060)  # the environment's address; nothing is reached
        clients.append(FakeClient(instrument))
        return clients[-1]

    def labcode(mission, cfg):
        return run_in_process(mission.directory, connect("10.5.1.156", 50060))

    def settle(instance, label, timeout):
        return instance.get_responses()

    manager = RunManager(config, connect=connect, settle=settle, run_labcode=labcode)
    mission = manager.prepare(workflow, env, boundary, directory, None)
    return manager.run(mission), mission, clients
