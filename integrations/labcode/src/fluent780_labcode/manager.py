"""The run manager: one FluentControl run around one ``lc run`` of a Fluent 780 workflow.

labcode runs every operation in a child process of its own, which opens its own SiLA2 connection and closes it when
the operation ends. The Tecan Fluent connector keeps a run opened with ``RunControl.StartRun`` in its back end across
connections, so the run is opened and ended here, around labcode, and not by any operation (labcode run management
specification for agents, 2026-11-14):

1. check the workflow, the environment and the labcode extension before anything is sent;
2. refuse if a FluentControl run is already open (never join or close someone else's run);
3. StartRun once, and record the mission (id, server, ``RunStarted``, ``RecordFolder``) in ``mission.json``;
4. ``lc run`` the workflow; every operation checks that the recorded run is still the open one before it sends;
5. when every operation completed: check the run is still ours, EndRun once, and check that no run is open.

When the run fails (an operation failed, labcode stopped, or anything here raised after StartRun), what happens to
the FluentControl run is the failure policy's:

- ``end-run`` (as the serial script of 2026-11-19 did): if the open run is still the one this mission opened,
  EndRun is sent once, after labcode has stopped (never while a command of this mission is being sent). The state
  is RUN_ENDED. If the run is not ours or its state cannot be read, nothing is sent and the state is UNCERTAIN.
- ``hold`` (section 3 of the specification): nothing is sent; the run is left open for an operator to inspect, and
  the state is UNCERTAIN.

Never: an automatic StartRun after a lost run, a resent command, DropTips or a plate move as cleanup.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from . import mission as m
from .mission import Mission, MissionError, serializable

DEVICE = "fluent_control"
"""The environment device that stands for the Tecan Fluent connector."""

ON_FAILURE = ("end-run", "hold")

DEFAULT_CONFIG = {
    "on_failure": "end-run",
    "cover_sites": {},
    "seconds_per_tick": 1.0,
    "first_plan_max_time": 30,
    "start_run_timeout": 300.0,
    "end_run_timeout": 300.0,
}


def load_yaml(path: str | Path) -> Any:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def connection_of(environment: dict) -> dict:
    """The SiLA2 connection of the ``fluent_control`` device."""
    for device in environment.get("devices", []):
        if device.get("id") == DEVICE:
            conn = (device.get("x-labcode") or {}).get("connection")
            if conn and conn.get("kind", "sila2") == "sila2":
                return conn
    raise MissionError(f"the environment has no device {DEVICE!r} with an x-labcode sila2 connection")


def with_endpoint(environment: dict, host: str, port: int) -> dict:
    """A copy of `environment` whose ``fluent_control`` connection points at `host`:`port`."""
    env = copy.deepcopy(environment)
    for device in env.get("devices", []):
        if device.get("id") == DEVICE:
            device["x-labcode"]["connection"].update(host=host, port=port)
    return env


def check_documents(workflow_path: Path, environment: dict) -> dict:
    """The front doors ``lc run`` uses (portable v0 and the labcode extension), run before StartRun. Returns the
    workflow with its ``$import``s expanded (what the mission runs)."""
    from labcode.dialect import validate_dialect
    from ofplang.run import front_door_check

    result = front_door_check(str(workflow_path), validate=True)
    if not result.ok:
        raise MissionError(f"the workflow is not valid: {result.diagnostics} {result.unsupported}")
    dialect = validate_dialect(result.document, environment)
    if not dialect.ok:
        raise MissionError(f"the labcode environment is not valid: {dialect.errors}")
    return result.document


def lc_run_command(mission: Mission, config: dict) -> list[str]:
    d = mission.directory
    return [
        sys.executable, "-m", "labcode", "run", str(d / "workflow.yaml"),
        "--env", str(d / "environment.yaml"),
        "--boundary", str(d / "boundary.yaml"),
        "-o", str(d / "status.yaml"),
        "--boundary-out", str(d / "result_boundary.yaml"),
        "--observation-out", str(d / "observation.yaml"),
        "--seconds-per-tick", str(config["seconds_per_tick"]),
        "--first-plan-max-time", str(config["first_plan_max_time"]),
        "--no-probe",
    ]  # fmt: skip


def run_lc(mission: Mission, config: dict) -> int:
    """Run ``lc run`` in a child process (the same interpreter, which also runs the operation scripts)."""
    with (mission.directory / "lc_run.log").open("w", encoding="utf-8") as log:
        return subprocess.run(
            lc_run_command(mission, config), stdout=log, stderr=subprocess.STDOUT, check=False
        ).returncode


def all_completed(mission: Mission) -> bool:
    path = mission.directory / "status.yaml"
    if not path.is_file():
        return False
    activities = (load_yaml(path) or {}).get("activities") or []
    return bool(activities) and all(a.get("status") == "completed" for a in activities)


class RunManager:
    """Open the run, let labcode drive the workflow, and end the run. `connect`, `settle` and `run_labcode` are
    injectable for tests (`run_labcode(mission, config) -> exit code`)."""

    def __init__(
        self,
        config: dict | None = None,
        *,
        connect: Callable[..., Any] | None = None,
        settle: Callable[..., Any] | None = None,
        run_labcode: Callable[[Mission, dict], int] = run_lc,
    ):
        self.config = {**DEFAULT_CONFIG, **(config or {})}
        if self.config["on_failure"] not in ON_FAILURE:
            raise MissionError(f"on_failure must be one of {ON_FAILURE}, not {self.config['on_failure']!r}")
        self.connect = connect
        self.settle = settle
        self.run_labcode = run_labcode

    # -- SiLA2 ----------------------------------------------------------------------------------------------------

    def _client(self, conn: dict) -> Any:
        connect = self.connect
        if connect is None:
            from sila2.client import SilaClient

            connect = SilaClient
        return connect(conn["host"], int(conn["port"]), insecure=bool(conn.get("insecure", False)))

    def _settle(self, instance: Any, label: str, timeout: float) -> Any:
        if self.settle is not None:
            return self.settle(instance, label, timeout)
        from labcode.sila2_commands import settle

        return settle(instance, label, timeout=timeout, poll=0.5)

    @staticmethod
    def _close(client: Any) -> None:
        close = getattr(client, "close", None)
        if callable(close):
            close()

    # -- the mission ----------------------------------------------------------------------------------------------

    def prepare(
        self, workflow: Path, environment: Path, boundary: Path, directory: Path, endpoint: tuple[str, int] | None
    ) -> Mission:
        """Check the documents and write the mission's copies of them. Nothing is sent."""
        directory.mkdir(parents=True, exist_ok=False)
        mission = Mission(directory)
        env = load_yaml(environment)
        if endpoint is not None:
            env = with_endpoint(env, *endpoint)
        conn = connection_of(env)
        expanded = check_documents(workflow, env)
        bnd = load_yaml(boundary)
        cell = bnd["boundary"]["inputs"]["cell"]
        cell["view"] = {**(cell.get("view") or {}), "mission_dir": str(mission.directory)}
        # the expanded workflow, so the mission holds exactly what was checked and run
        (directory / "workflow.yaml").write_text(yaml.safe_dump(expanded, sort_keys=False), encoding="utf-8")
        (directory / "environment.yaml").write_text(yaml.safe_dump(env, sort_keys=False), encoding="utf-8")
        (directory / "boundary.yaml").write_text(yaml.safe_dump(bnd, sort_keys=False, allow_unicode=True), "utf-8")
        mission.write(
            {
                "mission_id": directory.name,
                "workflow": str(workflow),
                "server": {
                    "host": conn["host"],
                    "port": int(conn["port"]),
                    "insecure": bool(conn.get("insecure", False)),
                },
                "on_failure": self.config["on_failure"],
                "cover_sites": self.config["cover_sites"],
                "run_started": None,
                "record_folder": None,
            }
        )
        mission.event("prepared", server=conn, endpoint_override=endpoint is not None)
        return mission

    def run(self, mission: Mission) -> int:
        """Open the run, run labcode and close the run. Returns 0 when everything completed and the run was ended."""
        conn = mission.data["server"]
        lock = mission.directory.parent / ".fluent780_labcode.lock"
        fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # one mission at a time from this folder
        os.write(fd, str(mission.directory).encode())
        os.close(fd)
        started: str | None = None
        try:
            client = self._client(conn)
            try:
                if client.RunControl.RunOpen.get():
                    raise MissionError("a FluentControl run is already open: refusing to join or close it")
                mission.set_state(m.OPENING)
                mission.event("sending", feature="RunControl", command="StartRun")
                response = self._settle(client.RunControl.StartRun(), "StartRun", self.config["start_run_timeout"])
                started = client.RunControl.RunStarted.get()
                data = mission.data
                data.update(run_started=started, record_folder=serializable(response))
                mission.write(data)
                mission.event("completed", feature="RunControl", command="StartRun", responses=serializable(response))
                mission.set_state(m.ACTIVE, run_started=started)
            finally:
                self._close(client)  # every operation connects anew, as labcode does

            code = self.run_labcode(mission, self.config)
            mission.event("labcode_finished", exit_code=code)
            if code != 0 or not all_completed(mission):
                raise MissionError(f"labcode did not complete the workflow (exit code {code}); see lc_run.log")

            mission.set_state(m.VERIFYING)
            client = self._client(conn)
            try:
                self._check_ours(client, started)
                mission.set_state(m.CLOSING)
                mission.event("sending", feature="RunControl", command="EndRun")
                response = self._settle(client.RunControl.EndRun(), "EndRun", self.config["end_run_timeout"])
                mission.event("completed", feature="RunControl", command="EndRun", responses=serializable(response))
                if client.RunControl.RunOpen.get():
                    raise MissionError("EndRun completed but a run is still open")
            finally:
                self._close(client)
            mission.set_state(m.COMPLETED)
            return 0
        except BaseException as exc:
            mission.event("mission_failed", error=f"{type(exc).__name__}: {exc}")
            self._after_failure(mission, started, exc)
            if not isinstance(exc, Exception):
                raise
            print(f"fluent780_labcode: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        finally:
            lock.unlink(missing_ok=True)

    def _check_ours(self, client: Any, started: str | None) -> None:
        run_open = client.RunControl.RunOpen.get()
        now = client.RunControl.RunStarted.get()
        if not run_open or started is None or now != started:
            raise MissionError(f"the open run is not this mission's (RunOpen={run_open}, RunStarted={now!r})")

    def _after_failure(self, mission: Mission, started: str | None, exc: BaseException) -> None:
        failure = f"{type(exc).__name__}: {exc}"
        if started is None:
            # Nothing was opened, or StartRun's outcome is not known: never end a run we cannot prove is ours.
            state = m.UNCERTAIN if mission.state().get("state") == m.OPENING else "REFUSED"
            mission.set_state(state, failure=failure)
            return
        if self.config["on_failure"] == "hold":
            mission.set_state(m.UNCERTAIN, failure=failure, run_left_open=True)
            return
        try:
            client = self._client(mission.data["server"])
            try:
                self._check_ours(client, started)
                mission.event("sending", feature="RunControl", command="EndRun", after_failure=True)
                response = self._settle(client.RunControl.EndRun(), "EndRun", self.config["end_run_timeout"])
                mission.event("completed", feature="RunControl", command="EndRun", responses=serializable(response))
                still_open = client.RunControl.RunOpen.get()
            finally:
                self._close(client)
        except Exception as end_exc:
            mission.set_state(m.UNCERTAIN, failure=failure, end_run_error=f"{type(end_exc).__name__}: {end_exc}")
            return
        if still_open:
            mission.set_state(m.UNCERTAIN, failure=failure, end_run_error="a run is still open after EndRun")
        else:
            mission.set_state(m.RUN_ENDED, failure=failure)


def new_mission_dir(root: Path) -> Path:
    return root / (datetime.datetime.now().strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8])


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m fluent780_labcode",
        description="Run a Fluent 780 labcode workflow inside one FluentControl run (StartRun ... lc run ... EndRun).",
    )
    sub = p.add_subparsers(dest="command", required=True)
    r = sub.add_parser("run", help="open a run, lc run the workflow, end the run")
    r.add_argument("workflow", type=Path)
    r.add_argument("--env", type=Path, required=True)
    r.add_argument("--boundary", type=Path, required=True)
    r.add_argument("--config", type=Path, help="run configuration YAML (failure policy, cover sites, pacing)")
    r.add_argument("--missions", type=Path, default=Path("missions"), help="folder for mission directories")
    r.add_argument("--on-failure", choices=ON_FAILURE, help="overrides on_failure of the run configuration")
    r.add_argument("--endpoint", help="HOST:PORT overriding the environment's fluent_control connection")
    args = p.parse_args(argv)

    config = load_yaml(args.config) if args.config else {}
    if args.on_failure:
        config["on_failure"] = args.on_failure
    endpoint = None
    if args.endpoint:
        host, _, port = args.endpoint.rpartition(":")
        endpoint = (host, int(port))
    try:
        manager = RunManager(config)
        mission = manager.prepare(
            args.workflow, args.env, args.boundary, new_mission_dir(args.missions.resolve()), endpoint
        )
    except (MissionError, OSError, ValueError) as exc:
        print(f"fluent780_labcode: {exc}", file=sys.stderr)
        return 2
    print(f"mission {mission.directory}", file=sys.stderr)
    return manager.run(mission)
