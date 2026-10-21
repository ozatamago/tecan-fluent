"""One FluentControl user at a time across every server on the Fluent PC.

Each server keeps "one operation at a time" for itself, but several servers (the combined one, the device servers,
the stand-alone ODTC server) talk to the same FluentControl, which runs one run at a time. Two servers that both
found FluentControl idle could start a run at the same moment, and the UniteLabs connector sends commands to the
channel opened last. This lock is a file on the Fluent PC that a server holds, through the operating system, while it
sends to FluentControl and for as long as it keeps a run open (StartRun to EndRun). The operating system releases it
when the holding process ends, so a crashed server never leaves it locked.

Next to the lock file, ``<lock>.owner.json`` says who holds it (server, operation, process, since when), so a refusal
can name the other server.
"""

from __future__ import annotations

import datetime
import json
import os
import pathlib

from .errors import BackendError


class SharedLock:
    def __init__(self, path: str, owner: str = ""):
        self.path = pathlib.Path(path)
        self.owner = owner or f"process {os.getpid()}"
        self._file = None

    @property
    def held(self) -> bool:
        return self._file is not None

    def _try_lock(self, f) -> bool:
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    def _unlock(self, f) -> None:
        f.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass

    @property
    def _owner_file(self) -> pathlib.Path:
        return self.path.with_name(self.path.name + ".owner.json")

    def holder(self) -> str:
        """Who holds the lock according to the owner file ("server: operation (since ...)"), or ""."""
        try:
            o = json.loads(self._owner_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return ""
        if o.get("hands_off"):  # held for another robot working on the deck (hands_off.py)
            h = o["hands_off"]
            return f"hands-off by {h.get('who', '?')} ({h.get('reason', '?')}, since {h.get('since', '?')})"
        return f"{o.get('owner', '?')}: {o.get('what', '?')} (since {o.get('since', '?')})"

    def acquire(self, what: str, extra: dict | None = None) -> None:
        """Take the lock or raise BackendError naming the server that holds it. Does nothing if already held.
        extra is added to the owner file (e.g. {"hands_off": {...}})."""
        if self._file is not None:
            self._write_owner(what, extra)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        f = open(self.path, "a+b")  # noqa: SIM115 - kept open while the lock is held
        if not self._try_lock(f):
            f.close()
            other = self.holder() or "another server"
            raise BackendError(f"FluentControl is in use by another server on the Fluent PC ({other})")
        self._file = f
        self._write_owner(what, extra)

    def release(self) -> None:
        if self._file is None:
            return
        f, self._file = self._file, None
        try:
            self._owner_file.unlink(missing_ok=True)
        except OSError:
            pass
        self._unlock(f)
        f.close()

    def other_holder(self) -> str:
        """The other server holding the lock now ("" if free or held by this server). Does not keep the lock."""
        if self._file is not None or not self.path.exists():
            return ""
        with open(self.path, "a+b") as f:
            if self._try_lock(f):
                self._unlock(f)
                return ""
        return self.holder() or "another server"

    def _write_owner(self, what: str, extra: dict | None = None) -> None:
        info = {
            "owner": self.owner,
            "what": what,
            "pid": os.getpid(),
            "since": datetime.datetime.now().isoformat(timespec="seconds"),
            **(extra or {}),
        }
        try:
            self._owner_file.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # the lock itself is what counts; the owner file only names the holder
