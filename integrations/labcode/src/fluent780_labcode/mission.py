"""The mission directory: what the run manager and every operation share on disk.

One labcode run of a Fluent 780 workflow is one *mission*. Its directory holds

- ``mission.json``  written once by the run manager after StartRun: the mission id, the server address, the run's
  ``RunStarted`` and ``RecordFolder``, the failure policy and how cover sites are resolved;
- ``state.json``    the run manager's state (OPENING, ACTIVE, VERIFYING, CLOSING, COMPLETED, UNCERTAIN, RUN_ENDED);
- ``events.jsonl``  one line per thing that happened, appended by the run manager and by every operation (each
  labcode operation runs in its own child process, so the file is the only shared record);
- the documents the run was started with and what ``lc run`` wrote back.

The operations find the directory through the ``mission_dir`` view field of the ``Workcell`` Object, which the run
manager puts into the run boundary.
"""

from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

MISSION_FILE = "mission.json"
STATE_FILE = "state.json"
EVENTS_FILE = "events.jsonl"

# Run manager states (labcode run management specification, 2026-11-14, section 3.1), plus RUN_ENDED: the run failed
# and, by the "end-run" failure policy, the run manager ended the FluentControl run after checking it was ours.
OPENING = "OPENING"
ACTIVE = "ACTIVE"
VERIFYING = "VERIFYING"
CLOSING = "CLOSING"
COMPLETED = "COMPLETED"
UNCERTAIN = "UNCERTAIN"
RUN_ENDED = "RUN_ENDED"


class MissionError(Exception):
    """A mission precondition does not hold. Nothing is sent to the instrument after this is raised."""


def serializable(value: Any) -> Any:
    """A SiLA2 response (named tuples, lists, numbers) as plain JSON values."""
    if hasattr(value, "_asdict"):
        return {k: serializable(v) for k, v in value._asdict().items()}
    if isinstance(value, dict):
        return {str(k): serializable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [serializable(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    return str(value)


def write_json(path: str | Path, value: Any) -> None:
    """Write JSON atomically (a reader never sees half a file)."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(serializable(value), indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


class Mission:
    """A mission directory."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory).resolve()

    @property
    def data(self) -> dict:
        path = self.directory / MISSION_FILE
        if not path.is_file():
            raise MissionError(
                f"{path} does not exist: start the workflow through the run manager "
                "(python -m fluent780_labcode run ...), which opens the FluentControl run first"
            )
        return read_json(path)

    def write(self, data: dict) -> None:
        write_json(self.directory / MISSION_FILE, data)

    def state(self) -> dict:
        path = self.directory / STATE_FILE
        return read_json(path) if path.is_file() else {}

    def set_state(self, state: str, **extra: Any) -> None:
        data = self.state()
        data.update(extra, state=state, updated=time.time())
        write_json(self.directory / STATE_FILE, data)
        self.event("state", state=state, **extra)

    def event(self, kind: str, **fields: Any) -> None:
        """Append one event line (flushed and synced, so it survives the process being stopped)."""
        mission_id = None
        path = self.directory / MISSION_FILE
        if path.is_file():
            mission_id = read_json(path).get("mission_id")
        record = {"time": time.time(), "pid": os.getpid(), "mission_id": mission_id, "kind": kind}
        record.update(serializable(fields))
        with (self.directory / EVENTS_FILE).open("a", encoding="utf-8") as out:
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            out.flush()
            os.fsync(out.fileno())

    def events(self) -> list[dict]:
        path = self.directory / EVENTS_FILE
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
