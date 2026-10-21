"""Backend that runs FluentControl statements (ODTC, Infinite, RGA, FCA, device macros, ...) through the UniteLabs
FluentControl connector on the Fluent PC. One backend allows one operation at a time; each server creates one and
shares it among its features.

Flow (one operation = one FluentControl run, unless a run was opened with StartRun)
----------------------------------------------------------------------------------
0. Check and record every definition the XML uses (definitions.Preflight). Refuse if something is missing or changed
1. Check the state. Refuse without doing anything unless it is EditMode or RunModeRunFinished
   (do not interfere with someone else's run, or with a run stopped at a dialog)
2. (RunModeRunFinished counts as idle. FluentControl has already closed the method, so go straight on)
3. PrepareMethod("OFML_ApiHost") -> RunMethod
4. Wait for the execution channel to open (OFML_ApiHost is then accepting external commands)
5. With a deck state (io/fluent/deck/state.py): RemoveLabware / AddLabware so that FluentControl's record matches the
   deck (bookkeeping only, recorded on its own)
6. ExecuteCommand(XML of each statement, e.g. the ODTC macro)
7. FinishCommand -> wait for the run to end (RunModeRunFinished)

The ODTC macro XML (io/odtc/macros.py) is identical to what ran on the device in the 2026-10-09 qPCR water demo
(odtc() in qpcr_water_demo.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses
import logging
import time

from unitelabs.cdk.config import Config

from ..odtc.macros import odtc_macro_xml
from .definitions import DefinitionCheckFailed, DefinitionsConfig, Preflight
from .errors import BackendError
from .shared_lock import SharedLock

logger = logging.getLogger(__name__)

API_HOST_METHOD = "OFML_ApiHost"
IDLE_STATES = {"EditMode", "RunModeRunFinished"}
STOP_STATES = {"RunModePaused", "RunModeStopOnError", "Unknown"}


def discover_port(server_uuid: str, timeout_s: float = 8.0) -> int | None:
    """Browse mDNS (_sila._tcp) and return the port of the SiLA2 server with the given UUID, or None if not found."""
    from zeroconf import ServiceBrowser, Zeroconf

    wanted = f"{server_uuid}._sila._tcp.local."
    found: dict[str, int] = {}

    class _Listener:
        def add_service(self, zc, type_, name):
            if name.lower() == wanted.lower():
                info = zc.get_service_info(type_, name, 3000)
                if info and info.port:
                    found["port"] = info.port

        def update_service(self, zc, type_, name):
            self.add_service(zc, type_, name)

        def remove_service(self, zc, type_, name):
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, "_sila._tcp.local.", _Listener())
        deadline = time.monotonic() + timeout_s
        while "port" not in found and time.monotonic() < deadline:
            time.sleep(0.2)
    finally:
        zc.close()
    return found.get("port")


@dataclasses.dataclass
class FluentBackendConfig(Config):
    """Where to reach the UniteLabs FluentControl connector."""

    host: str = "10.5.1.156"
    port: int = 51822
    """Port of the UniteLabs connector. It is configured as port 0, so it changes whenever that connector restarts.
    If the connection fails, look up the unitelabs_uuid server via mDNS and take only the port from it (keep using host
    as the address, because that connector advertises only 127.0.0.1 and 169.254.* over mDNS)."""
    unitelabs_uuid: str = "6f944f98-9763-4b26-9467-681cf42c9e18"
    dry_run: bool = True
    """While True, the XML is only built and logged; nothing is sent to the Fluent."""
    dry_run_seconds: float = 0.0
    """Seconds to wait in a dry run while pretending to send (for checking how progress is delivered)."""
    ssh_target: str = "Tecan@10.5.1.156"
    """SSH target for reading temperatures from the FluentControl log (must allow key authentication)."""
    sensor_script: str = r"C:\Users\Tecan\OFML\tools\odtc_last_sensor_values.ps1"
    """Location of the reader script (scripts/windows/odtc_last_sensor_values.ps1) on the Fluent PC."""
    channel_timeout_s: float = 300.0
    finish_timeout_s: float = 180.0
    api_channel: str = "ofml"
    """Name of the channel OFML_ApiHost opens. Commands are sent only after a channel with this name is open."""
    definitions: DefinitionsConfig = dataclasses.field(default_factory=DefinitionsConfig)
    """Checking and recording of the FluentControl definitions each operation uses."""
    shared_lock: str = ""
    """Lock file shared by every server on the Fluent PC (e.g. C:\\Users\\Tecan\\OFML\\state\\fluentcontrol.lock), so
    that only one server at a time sends to FluentControl or keeps a run open. Empty: no lock (one server only)."""


class FluentControlBackend:
    def __init__(self, config: FluentBackendConfig):
        self.config = config
        self._lock = asyncio.Lock()
        self.shared = SharedLock(config.shared_lock) if config.shared_lock else None
        """The lock shared with the other servers on the Fluent PC (None when not configured)."""
        self._client = None
        self.current_operation = ""
        """Description of the operation currently running (e.g. "ODTC: SiLA-ODTC_OpenDoor"). Empty when idle."""
        self.preflight = Preflight(config.definitions, config.dry_run)
        self.session_labware: dict[str, str] = {}
        """Labware added with AddLabware in the open run: label -> labware type."""
        self.tips: dict[int, dict] = {}
        """Tips mounted in the open run: channel (1-8) -> {"type", "group", "capacity", "aspirated", "volume"}."""
        self.cameras = None
        """DeckCameras: images of the deck at StartRun and EndRun (set by the server; None means no images)."""
        self._session = None
        """Run opened by StartRun: {"rel": records folder, "started": str, "commands": int}. None when none is open."""
        self.deck = None
        """DeckState registered at the start of every run (set by the server with attach_deck; None means none)."""
        self.hands_off = None
        """HandsOff of this server (set by the server): while it is held, every operation is refused."""

    def attach_deck(self, deck) -> None:
        """Register this deck state at the start of every run, and refuse labware labels it does not know."""
        self.deck = deck
        self.preflight.labware_check = lambda labels, base, steps: deck.check_labels(
            steps, base, set(self.session_labware)
        )

    def write_record(self, rel: str, data: dict) -> None:
        """Store a small JSON record at OFML\\records\\<rel> (e.g. deck\\<time>_PlaceLabware.json)."""
        import json
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / rel.rsplit("\\", 1)[-1]
            f.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            self.preflight.store(f, rel, [])

    # ---- Synchronous SiLA2 client (called from a worker thread)
    def _c(self):
        if self._client is None:
            from sila2.client import SilaClient

            try:
                self._client = SilaClient(self.config.host, self.config.port, insecure=True)
            except Exception as first:  # noqa: BLE001 - if it cannot connect, look up the port again via mDNS
                port = discover_port(self.config.unitelabs_uuid)
                if port is None or port == self.config.port:
                    raise BackendError(
                        f"Cannot connect to the UniteLabs connector ({self.config.host}:{self.config.port}): {first}"
                    ) from None
                logger.info("UniteLabs connector port had changed from %s to %s", self.config.port, port)
                self.config.port = port
                self._client = SilaClient(self.config.host, port, insecure=True)
        return self._client

    def _state(self) -> str:
        prop = self._c().RuntimeController.State
        if hasattr(prop, "get"):
            return str(prop.get())
        sub = prop.subscribe()
        try:
            return str(next(iter(sub)))
        finally:
            sub.cancel()

    def _our_channel_open(self) -> bool:
        c = self._c()
        try:
            return c.ExecutionChannelController.Channel.get() == self.config.api_channel and bool(
                c.ExecutionChannelController.IsAlive.get()
            )
        except Exception:  # noqa: BLE001 - raises while no channel exists yet
            return False

    def _active_dialogs(self) -> list[str]:
        try:
            return [
                f"{d.DialogIdentifier}: {d.Description.strip()}" for d in self._c().RunController.ActiveDialogs.get()
            ]
        except Exception:  # noqa: BLE001 - carry on even if this cannot be read
            return []

    def _wait(self, predicate, timeout: float, what: str, report) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self._state()
            if state in STOP_STATES:
                dialogs = self._active_dialogs()
                raise BackendError(f"FluentControl went to {state} during {what}. {' / '.join(dialogs)}")
            if predicate(state):
                return state
            report(state)
            time.sleep(2)
        raise BackendError(f"{what} did not finish within {timeout:.0f} s (state {self._state()})")

    def _run_macro(self, name: str, settings: str | None, report) -> float:
        return self._run_steps([(name, odtc_macro_xml(name, settings))], report)[0]

    def _run_steps(self, steps: list[tuple[str, str]], report, extra: dict | None = None, post=None) -> list[float]:
        """Send XML commands in order. Returns the seconds each command took.

        Before sending, every definition the commands use is checked and recorded (refused if missing or changed).
        Without an open run (StartRun), the commands get a FluentControl run of their own that is ended afterwards.
        Inside an open run they are only sent, so tips and labware positions carry over to the next command.
        If a command fails, the remaining ones are not sent. report receives each command's label before it is sent.
        """
        what = self.current_operation or steps[0][0]
        session = self._session["rel"] if self._session else ""
        # a run of their own starts from the worktable, so the deck state is registered first (an open run had it
        # registered at StartRun)
        deck = None if self._session else self._deck_begin(session)
        try:
            record = self.preflight.begin(steps, what, session, extra)
        except DefinitionCheckFailed as exc:
            if deck is not None:
                deck[1].finish({"status": "not sent", "reason": "the operation was refused"})
            raise BackendError(str(exc)) from None
        if self._session:
            self._session["commands"] += 1
        try:
            if self.config.dry_run:
                if deck is not None:
                    self._deck_send(deck, report)
                for label, xml in steps:
                    logger.info("dry-run: would have sent %s\n%s", label, xml)
                    report("dry-run")
                    report(label)
                time.sleep(self.config.dry_run_seconds)
                durations = [0.0 for _ in steps]
            elif self._session:
                durations = self._execute(steps, report)
            else:
                self._open_run(report)
                try:
                    if deck is not None:
                        self._deck_send(deck, report)
                    durations = self._execute(steps, report)
                finally:
                    self._close_run(report)
        except Exception as exc:
            if deck is not None and not deck[3]:
                deck[1].finish({"status": "not sent", "reason": f"{type(exc).__name__}: {exc}"})
            record.finish({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            raise
        result = {"status": "ok", "seconds": durations, "in_open_run": bool(self._session)}
        if post is not None and not self.config.dry_run:
            # e.g. what FluentControl's log says the commands did; added to the record, never fails the operation
            try:
                result.update(post())
            except Exception as exc:  # noqa: BLE001
                result["post_error"] = f"{type(exc).__name__}: {exc}"
        record.finish(result)
        if not self.config.dry_run:
            self.preflight.forget_dry_runs()  # dry-run records are only kept until a real operation has run
        return durations

    # ---- The deck state at the start of a run
    def _deck_begin(self, session: str):
        """Check the deck registration and start its record: [steps, record, info, sent], or None when there is no
        deck state or nothing to register. Refuses (BackendError) if the deck state cannot be read or a definition
        does not fit."""
        if self.deck is None:
            return None
        steps, info = self.deck.registration()
        if not steps:
            return None
        try:
            record = self.preflight.begin(steps, "Deck: registration at run start", session, {"deck": info})
        except DefinitionCheckFailed as exc:
            raise BackendError(f"Registering the deck state was refused: {exc}") from None
        return [steps, record, info, False]

    def _deck_send(self, deck: list, report) -> None:
        """Send the deck registration (only logged in a dry run) and finish its record."""
        steps, record, info, _ = deck
        deck[3] = True
        try:
            if self.config.dry_run:
                for label, xml in steps:
                    logger.info("dry-run: would have sent %s\n%s", label, xml)
                    report(f"Run start: {label}")
                durations = [0.0 for _ in steps]
            else:
                durations = self._execute([(f"Run start: {label}", xml) for label, xml in steps], report)
        except Exception as exc:
            record.finish({"status": "failed", "error": f"{type(exc).__name__}: {exc}"})
            raise BackendError(f"Registering the deck state at the start of the run failed: {exc}") from None
        record.finish({"status": "ok", "seconds": durations, "deck_version": info["version"]})
        if self._session:  # registered with AddLabware: known in this run like labware added with Labware.AddLabware
            self.session_labware.update(info["added"])
        try:
            self.deck.registered(info)
        except Exception as exc:  # noqa: BLE001 - FluentControl has the racks already; only the note is missing
            logger.warning("Could not note the racks registered as full: %s", exc)

    def _open_run(self, report) -> None:
        """Start OFML_ApiHost and wait until its execution channel accepts commands."""
        c = self._c()
        if not c.FluentController.IsAttached.get():
            raise BackendError("The UniteLabs connector is not attached to FluentControl")
        state = self._state()
        # State is the last state-change notification the UniteLabs connector received. On 2026-10-15 it was mistaken
        # for a stale value, but FluentControl was actually stuck in StartUp at a startup dialog. Do not rely on IsReady
        if state not in IDLE_STATES:
            dialogs = self._active_dialogs()
            raise BackendError(
                f"Not starting because FluentControl is in {state} (check for other runs or dialogs)"
                + (f". Open dialogs: {' / '.join(dialogs)}" if dialogs else "")
            )
        # A run stopped at a dialog (e.g. a door opened) can leave FluentControl in RunModeRunFinished with the dialog
        # still open. PrepareMethod is then refused ("Only allowed in Edit Mode!") and the UniteLabs connector does not
        # answer for 2 minutes (2026-10-20). An empty "Unused ID" dialog stays after FluentControl restarts and does
        # not block a run.
        dialogs = [d for d in self._active_dialogs() if d.split(":", 1)[-1].strip()]
        if dialogs:
            raise BackendError(f"Not starting because FluentControl has open dialogs: {' / '.join(dialogs)}")

        report("PrepareMethod")
        c.RuntimeController.PrepareMethod(API_HOST_METHOD)
        c.RuntimeController.RunMethod()
        deadline = time.monotonic() + self.config.channel_timeout_s
        # The UniteLabs connector reports the most recently opened channel. If a record of a channel opened by another
        # client remains, IsAlive is True from the start (2026-10-15, "main" from a parallel test lingered), so the
        # channel name is checked as well
        while not self._our_channel_open():
            state = self._state()
            if state in STOP_STATES:
                raise BackendError(f"Went to {state} while starting the run. {' / '.join(self._active_dialogs())}")
            if state == "RunModeQueryVariables":
                c.RuntimeController.CloseQueryAtStartupDialog(True)
            if time.monotonic() > deadline:
                raise BackendError(
                    f"The execution channel did not open (state {state}). {' / '.join(self._active_dialogs())}"
                )
            report(f"waiting channel ({state})")
            time.sleep(2)

    def _execute(self, steps: list[tuple[str, str]], report) -> list[float]:
        c = self._c()
        durations: list[float] = []
        for label, xml in steps:
            report(label)
            t0 = time.monotonic()
            c.ExecutionChannelController.ExecuteCommand(xml)
            durations.append(time.monotonic() - t0)
        return durations

    def _close_run(self, report) -> None:
        """End the run and return to idle. Failures are logged, not raised (used in cleanup)."""
        try:
            self._c().ExecutionChannelController.FinishCommand()
            # When the run ends, FluentControl closes the method itself and goes to RunModeRunFinished.
            # CloseMethod is not sent: it is refused with "No method loaded to be closed." (confirmed 2026-10-15)
            self._wait(lambda s: s in IDLE_STATES, self.config.finish_timeout_s, "the end of the run", report)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed while cleaning up the run: %s", exc)

    # ---- Holding one run open across commands (StartRun / EndRun)
    def _write_session(self, info: dict) -> None:
        import json
        import pathlib
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            f = pathlib.Path(tmp) / "session.json"
            f.write_text(json.dumps(info))
            self.preflight.store(f, self._session_rel(info["started"]) + "\\session.json", [])

    def _deck_images(self, tag: str) -> list:
        """Images of the deck from all cameras into the open run's record (never fails the run)."""
        if self.cameras is None or not self.cameras.config.capture_on_run or not self._session:
            return []
        out_dir = f"{self.config.definitions.remote_dir.rstrip(chr(92))}\\records\\{self._session['rel']}\\images"
        try:
            return self.cameras.capture(list(self.cameras.config.cameras), out_dir, tag)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Deck images (%s) failed: %s", tag, exc)
            return [{"status": "error", "error": str(exc)[:300]}]

    def _session_rel(self, started: str) -> str:
        return f"runs\\{started}_session" + ("_dry-run" if self.config.dry_run else "")

    def _start_session(self, report) -> str:
        import datetime

        if self._session:
            raise BackendError(f"A run is already open (since {self._session['started']})")
        if self.deck is not None:
            self.deck.load()  # refuse before the run starts if the deck state cannot be read
        if not self.config.dry_run:
            self._open_run(report)
        started = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        self._session = {"rel": self._session_rel(started), "started": started, "commands": 0}
        self.session_labware = {}
        self.tips = {}
        try:
            deck = self._deck_begin(self._session["rel"])
            if deck is not None:
                self._deck_send(deck, report)
        except Exception:
            self._session = None
            if not self.config.dry_run:
                self._close_run(report)
            raise
        self._session["images_start"] = self._deck_images("start")
        self._write_session(
            {"started": started, "dry_run": self.config.dry_run, "images_start": self._session["images_start"]}
        )
        return self.preflight.location(self._session["rel"])

    def _end_session(self, report) -> int:
        import datetime

        if not self._session:
            raise BackendError("No run is open")
        if self.tips:
            raise BackendError(f"Tips are still mounted on channels {sorted(self.tips)}: drop them first (DropTips)")
        images_end = self._deck_images("end")
        session, self._session = self._session, None
        if not self.config.dry_run:
            self._close_run(report)
        self._write_session(
            {
                "started": session["started"],
                "dry_run": self.config.dry_run,
                "ended": datetime.datetime.now().strftime("%Y%m%d-%H%M%S"),
                "commands": session["commands"],
                "images_start": session.get("images_start", []),
                "images_end": images_end,
            }
        )
        return session["commands"]

    async def start_run(self, report=lambda _: None) -> str:
        """Open one FluentControl run that later commands share (tips and positions carry over). Returns the record
        folder."""
        async with self._exclusive("Run: StartRun"):
            return await asyncio.to_thread(self._guarded, self._start_session, report)

    async def end_run(self, report=lambda _: None) -> int:
        """End the run opened by start_run. Returns the number of operations sent in it."""
        async with self._exclusive("Run: EndRun"):
            return await asyncio.to_thread(self._guarded, self._end_session, report)

    @property
    def run_open(self) -> bool:
        return self._session is not None

    @property
    def run_started(self) -> str:
        return self._session["started"] if self._session else ""

    @property
    def session_dir(self) -> str:
        """Folder of the open run's record on the Fluent PC, or "" when no run is open."""
        if not self._session:
            return ""
        return f"{self.config.definitions.remote_dir.rstrip(chr(92))}\\records\\{self._session['rel']}"

    # ---- Entry points called from the Features
    async def run_macro(self, name: str, settings: str | None = None, report=lambda _: None) -> float:
        """Run one ODTC macro and return the seconds the macro itself took. Only one at a time."""
        async with self._exclusive(f"ODTC: {name}" + (f" {settings}" if settings else "")):
            return await asyncio.to_thread(self._guarded, self._run_macro, name, settings, report)

    async def run_steps(
        self, steps: list[tuple[str, str]], report=lambda _: None, what: str = "", extra: dict | None = None, post=None
    ) -> list[float]:
        """Send several XML commands in order within one run (e.g. load, measure and unload in a single run).
        extra is added to the record's manifest (e.g. the liquid class settings used)."""
        what = what or (steps[0][0] if len(steps) == 1 else f"{steps[0][0]} and {len(steps) - 1} more commands")
        async with self._exclusive(what):
            return await asyncio.to_thread(self._guarded, self._run_steps, steps, report, extra, post)

    @contextlib.asynccontextmanager
    async def _exclusive(self, what: str):
        """Only one operation sending commands to FluentControl may run at a time in this server. A refusal names it."""
        if self._lock.locked():
            raise BackendError(f"Another operation is running ({self.current_operation})")
        if self.hands_off is not None:
            self.hands_off.check()  # refuses while another robot works on the deck
        async with self._lock:
            if self.shared is not None:
                self.shared.acquire(what)  # refuses while another server on the Fluent PC uses FluentControl
            self.current_operation = what
            try:
                yield
            finally:
                self.current_operation = ""
                # a run held open by StartRun keeps the lock until EndRun
                if self.shared is not None and self._session is None:
                    self.shared.release()

    # ---- Temperature (the ReadActualTemperature result is not returned to FluentControl; only the driver log has it)
    def _ssh_ps(self, args: str) -> str:
        from . import remote

        out = remote.run(self.config.ssh_target, f"powershell -NoProfile -ExecutionPolicy Bypass {args}", 120)
        if out.returncode != 0:
            raise BackendError(f"Command on the Fluent PC failed: {out.stderr.decode(errors='replace')[:200]}")
        return out.stdout.decode("utf-8", errors="replace").replace("\r", "")

    def _read_sensor_values(self, report) -> dict[str, float | str]:
        import html
        import re

        if self.config.dry_run:
            self._run_macro("SiLA-ODTC_ReadActualTemperature", None, report)
            return {"timestamp": "dry-run"}
        since = self._ssh_ps("-Command \"Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'\"").strip()
        self._run_macro("SiLA-ODTC_ReadActualTemperature", None, report)
        for _ in range(10):  # the log write can lag slightly
            out = self._ssh_ps(f'-File "{self.config.sensor_script}" -Since "{since}"')
            if out.startswith("LOGTIME"):
                text = out
                for _ in range(4):
                    text = html.unescape(text)
                m = re.search(r'<SensorValues timestamp="([^"]+)">(.*?)</SensorValues>', text, re.S)
                if m:
                    values: dict[str, float | str] = {"timestamp": m.group(1)}
                    values.update({k: int(v) / 100 for k, v in re.findall(r"<(\w+)>(-?\d+)</\1>", m.group(2))})
                    return values
            time.sleep(2)
        raise BackendError("No temperature record found in the FluentControl log")

    async def read_sensor_values(self, report=lambda _: None) -> dict[str, float | str]:
        """Send ReadActualTemperature and read the result from the FluentControl log. Values are in degC."""
        async with self._exclusive("ODTC: read temperature"):
            return await asyncio.to_thread(self._guarded, self._read_sensor_values, report)

    def _guarded(self, fn, *args):
        """On an unexpected exception from a backend call, drop the connection (rebuilt next time); raise
        BackendError."""
        try:
            return fn(*args)
        except BackendError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._client = None
            raise BackendError(
                f"Communication with the UniteLabs connector failed: {type(exc).__name__}: {str(exc)[:300]}"
            ) from None

    # ---- Status (does not move the device)
    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @property
    def lock_owner(self) -> str:
        return self.shared.owner if self.shared is not None else ""

    @lock_owner.setter
    def lock_owner(self, name: str) -> None:
        """The name other servers see when this one holds the shared lock (set to the SiLA server name)."""
        if self.shared is not None:
            self.shared.owner = name

    @property
    def hands_off_text(self) -> str:
        """'hands-off by <who> (<reason>, since ...)' while this server holds hands-off, else ""."""
        return self.hands_off.text if self.hands_off is not None else ""

    def other_server(self) -> str:
        """The other server on the Fluent PC that uses FluentControl now ("" if none or no shared lock)."""
        return self.shared.other_holder() if self.shared is not None else ""

    def _status(self) -> tuple[str, list[str]]:
        return self._state(), self._active_dialogs()

    async def fluent_status(self) -> tuple[str, list[str]]:
        """FluentControl state (the last notification the UniteLabs connector received) and the open dialogs."""
        return await asyncio.to_thread(self._guarded, self._status)
