"""The deck state: what is where on the deck, kept as data on the Fluent PC (docs/deck_state_spec.md).

FluentControl resets labware to the worktable definition at the start of every run, and labware added with
AddLabware exists only until the run ends. The deck state says how the real deck differs from the base worktable
(the worktable OFML_ApiHost uses): labware put on the deck by a person or another robot, base-worktable labware moved
or taken off, the tip state of racks put in, and optionally what the labware contains. At the start of every run the
backend brings FluentControl's record in line with it (registration: RemoveLabware / AddLabware, bookkeeping only),
and the RGA commands update it after each move. The labware tracker of PlateTransfer is a view on it.

The file (setting deck.state_file, ``C:\\Users\\Tecan\\OFML\\state\\deck.json`` on the Fluent PC) is read before
every use and written atomically (a temporary file, then replaced):

    {"labware": {"Plate_A[001]": {"type": "96 Well Flat", "location": "Nest7mm_Pos_3", "site": 14, "base": null,
                                  "lid": "Lid_9mm[001]", "placed_by": "Franka", "placed_at": "2026-10-21T10:00:00",
                                  "contents": {"A1": {"liquid": "water", "volume_ul": 150}}},
                 "96 Well Flat_Custom[001]": {"type": "96 Well Flat_Custom", "location": "Regrip_Pos", "site": 1,
                                              "base": {"location": "Nest7mm_Pos", "site": 6}, "moved_by": "RGA"}},
     "base_worktable": "WT2411004293_Ver.0.5_OFML", "version": 12}

- "base" is the position of the labware on the base worktable, or null for labware that is not part of it. It is
  looked up in the definition index when the entry is made, so the start of a run needs no index.
- Base-worktable labware is listed only while it is away from its base position ("location": null when it was taken
  off the deck) or while something else is recorded for it (contents, tips, a lid).
- "version" increases with every change; every change is also written to the records
  (``OFML\\records\\deck\\<time>_<command>.json``), and the records of the operations say which version they used.
- Without the file, the positions of the labware tracker (``labware_positions.json``) are taken over once; while the
  new file cannot be written (or in a dry run) the old file keeps being read.
- In a dry run, changes are kept in memory only (as the labware tracker does).
"""

import contextlib
import copy
import dataclasses
import datetime
import json
import logging
import os
import pathlib
import re
import tempfile

from unitelabs.cdk.config import Config

from ...fluentcontrol.definitions import DefinitionCheckFailed, DefinitionView, FluentPc, _unescape, extract_references
from ...fluentcontrol.errors import BackendError
from ..gripper.statements import add_labware_xml, remove_labware_xml

logger = logging.getLogger(__name__)

DECK_FILE = r"C:\Users\Tecan\OFML\state\deck.json"
"""Where the Fluent PC example configurations keep the deck state."""
TIP_KINDS = ("full", "as is")
"""A fresh rack, or a rack taken out earlier and put back."""
WELL = re.compile(r"[A-Z]{1,2}[1-9][0-9]{0,2}")


@dataclasses.dataclass
class DeckConfig(Config):
    """The deck state of this instrument and the hands-off limit (docs/deck_state_spec.md)."""

    state_file: str = ""
    """File holding the deck state, e.g. C:\\Users\\Tecan\\OFML\\state\\deck.json. A Windows path (C:\\...) is on the
    Fluent PC; any other path is on the computer running the connector (used by the tests). Empty: no deck state (the
    Deck commands are refused, runs start from the worktable as before, and the RGA positions stay in
    plates.positions_file)."""
    base_worktable: str = ""
    """Name of the worktable the deck state describes. It must be the worktable OFML_ApiHost uses
    (fluent.definitions.workspace); empty means that one."""
    handoff_sites: list = dataclasses.field(default_factory=list)
    """Positions other robots may use to hand labware over, e.g. [{"location": "Nest7mm_Pos", "site": 1}]. Kept for
    the hand-over commands to come; nothing uses them yet."""
    hands_off_max_minutes: float = 30.0
    """Default and upper limit of HandsOff.Begin's MaxMinutes."""


class _File:
    """A text file on the Fluent PC (over SSH from another computer, directly on the Fluent PC itself)."""

    def __init__(self, path: str, pc: FluentPc | None):
        self.path = path
        self.remote = bool(re.match(r"^[A-Za-z]:\\", path)) and os.name != "nt"
        self.pc = pc

    def read(self) -> str | None:
        if not self.remote:
            path = pathlib.Path(self.path).expanduser()
            return path.read_text(encoding="utf-8") if path.exists() else None
        if self.pc is None:
            raise BackendError(f"No connection to the Fluent PC configured for {self.path}")
        try:
            return self.pc.read_file(self.path)
        except DefinitionCheckFailed as exc:
            raise BackendError(f"Cannot read {self.path} on the Fluent PC: {exc}") from None

    def write(self, text: str) -> None:
        if self.remote:
            try:
                self.pc.replace_file(self.path, text)
            except DefinitionCheckFailed as exc:
                raise BackendError(f"Cannot save {self.path} on the Fluent PC: {exc}") from None
            return
        path = pathlib.Path(self.path).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp)
            raise


def _position(entry: dict) -> str:
    return f"{entry.get('location')}[{entry.get('site')}]"


def _at_base(entry: dict) -> bool:
    base = entry.get("base")
    return bool(base) and entry.get("location") == base["location"] and int(entry.get("site") or 0) == int(base["site"])


class DeckState:
    def __init__(
        self,
        config: DeckConfig,
        worktable: str,
        pc: FluentPc | None = None,
        persist: bool = True,
        definitions=None,
        recorder=None,
        legacy_file: str = "",
        legacy_labware: dict | None = None,
        clock=None,
    ):
        self.config = config
        self.worktable = worktable
        """The worktable OFML_ApiHost uses (fluent.definitions.workspace)."""
        self.file = _File(config.state_file, pc)
        self.legacy = _File(legacy_file, pc) if legacy_file else None
        """labware_positions.json of the labware tracker, taken over when the deck state file does not exist yet."""
        self.legacy_labware = legacy_labware or {}
        """The movable labware of the tracker (plates.labware): label -> {"type", "base_location", "base_site"}."""
        self.persist = persist
        self.definitions = definitions
        """Callable returning a DefinitionView (labware types, locations and labware of the base worktable)."""
        self.recorder = recorder
        """Callable (relative path under OFML\\records, data) that stores a record of each change."""
        self.clock = clock or datetime.datetime.now
        self._dry: dict | None = None
        """The state changed in a dry run (never written anywhere)."""

    # ---- reading and writing
    @property
    def base_worktable(self) -> str:
        return self.config.base_worktable or self.worktable

    def _check_worktable(self) -> None:
        if self.config.base_worktable and self.config.base_worktable != self.worktable:
            raise BackendError(
                f"deck.base_worktable '{self.config.base_worktable}' is not the worktable OFML_ApiHost uses "
                f"(fluent.definitions.workspace '{self.worktable}')"
            )

    def _now(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    def load(self) -> dict:
        """The current deck state, read fresh: {"labware": {...}, "base_worktable": ..., "version": n}."""
        self._check_worktable()
        if self._dry is not None:
            return copy.deepcopy(self._dry)
        text = self.file.read()
        if not text or not text.strip():
            return self._from_legacy()
        state = json.loads(text)
        if state.get("base_worktable", self.base_worktable) != self.base_worktable:
            raise BackendError(
                f"The deck state {self.config.state_file} describes worktable {state['base_worktable']}, "
                f"not {self.base_worktable}"
            )
        state.setdefault("labware", {})
        state.setdefault("version", 0)
        state["base_worktable"] = self.base_worktable
        return state

    def _from_legacy(self) -> dict:
        state = {"labware": {}, "base_worktable": self.base_worktable, "version": 0}
        text = self.legacy.read() if self.legacy is not None else None
        positions = json.loads(text) if text and text.strip() else {}
        if not positions:
            return state
        now = self._now()
        for label, (location, site) in positions.items():
            spec = self.legacy_labware.get(label)
            if not spec:
                logger.warning("%s in %s is not in plates.labware; not taken over", label, self.legacy.path)
                continue
            state["labware"][label] = {
                "type": spec["type"],
                "location": location,
                "site": int(site),
                "base": {"location": spec["base_location"], "site": int(spec["base_site"])},
                "moved_by": "RGA",
                "moved_at": now,
            }
        state["migrated_from"] = self.legacy.path
        if self.persist:
            state["version"] = 1
            try:
                self.file.write(json.dumps(state, ensure_ascii=False, indent=1))
            except BackendError as exc:  # keep reading the old file until the new one can be written
                logger.warning("Could not take over %s into the deck state: %s", self.legacy.path, exc)
                state["version"] = 0
                return state
            logger.info("Took over %s into the deck state %s", self.legacy.path, self.config.state_file)
            self._record("Migrate", {"from": self.legacy.path, "labware": state["labware"], "version": 1})
        return state

    def _save(self, state: dict, read_version: int) -> None:
        if not self.persist:
            self._dry = copy.deepcopy(state)
            return
        current = self.file.read()
        if current and current.strip() and json.loads(current).get("version", 0) != read_version:
            raise BackendError("The deck state was changed meanwhile (by another server?); send the command again")
        self.file.write(json.dumps(state, ensure_ascii=False, indent=1))

    def _record(self, command: str, data: dict) -> None:
        """Keep a record of a change (never fails the change)."""
        if self.recorder is None:
            return
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
        try:
            self.recorder(f"deck\\{stamp}_{command}.json", {"command": command, "time": self._now(), **data})
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not record the deck change %s: %s", command, exc)

    def _change(self, command: str, args: dict, fn) -> int:
        """Apply fn to the labware entries, save, record, and return the new version."""
        state = self.load()
        version = state["version"]
        detail = fn(state["labware"]) or {}
        state["version"] = version + 1
        self._save(state, version)
        self._record(command, {"args": args, "version_before": version, "version": state["version"], **detail})
        return state["version"]

    # ---- checks against the definitions
    def _view(self, need: bool = True) -> DefinitionView | None:
        """The definition view; None when it cannot be had in a dry run (or need is False)."""
        if self.definitions is None:
            return None
        try:
            return self.definitions()
        except DefinitionCheckFailed as exc:
            if self.persist and need:
                raise BackendError(f"Cannot check the FluentControl definitions: {exc}") from None
            logger.warning("Deck state: definitions not checked (%s)", exc)
            return None

    @staticmethod
    def _occupied(entries: dict, view: DefinitionView | None) -> dict[tuple, str]:
        """(location, site) -> label of what is there according to the deck state and the base worktable."""
        taken: dict[tuple, str] = {}
        if view is not None:
            for label, b in view.labware.items():
                if label not in entries:
                    taken[(b["location"], int(b["site"]))] = label
        for label, e in entries.items():
            if e.get("location"):
                taken[(e["location"], int(e["site"]))] = label
        return taken

    def _check_position(self, view, entries: dict, label: str, location: str, site: int) -> None:
        if view is not None:
            if location not in view.sites:
                raise BackendError(f"Location '{location}' is not on worktable {view.worktable}")
            if not 1 <= site <= view.sites[location]:
                raise BackendError(f"{location}[{site}] does not exist ({location} has {view.sites[location]} sites)")
        other = self._occupied(entries, view).get((location, site))
        if other and other != label:
            raise BackendError(f"{location}[{site}] is taken by {other} in the deck state")

    @staticmethod
    def _base_of(view: DefinitionView | None, label: str) -> dict | None:
        if view is None or label not in view.labware:
            return None
        b = view.labware[label]
        return {"location": b["location"], "site": int(b["site"])}

    @staticmethod
    def _prune(entries: dict, label: str) -> None:
        """Base-worktable labware back at its base position with nothing else recorded is not listed."""
        e = entries.get(label)
        if e and _at_base(e) and not (e.get("contents") or e.get("tips") or e.get("lid")):
            del entries[label]

    # ---- changes
    def place(
        self,
        label: str,
        labware_type: str,
        location: str,
        site: int,
        lid: str = "",
        placed_by: str = "",
        tips: dict | None = None,
        command: str = "PlaceLabware",
    ) -> int:
        """Record that a labware was put on the deck. Refused if the site is taken, the type is not defined in
        FluentControl, or the location/site is not on the base worktable. Returns the new version."""
        label, site = label.strip(), int(site)
        if not label or not labware_type.strip() or not location.strip():
            raise BackendError("Label, labware type and location must not be empty")
        args = {"label": label, "type": labware_type, "location": location, "site": site, "lid": lid, "by": placed_by}

        def fn(entries: dict) -> dict:
            view = self._view()
            warnings = [] if view is not None else ["dry run: definitions not checked"]
            if view is not None and labware_type not in view.labware_types:
                raise BackendError(f"Labware type '{labware_type}' is not defined in FluentControl")
            before = entries.get(label)
            base = self._base_of(view, label) or (before or {}).get("base")
            current = before if before is not None else (view.labware.get(label) if view is not None else None)
            on_deck = current is not None and current.get("location") is not None
            if on_deck and not (tips is not None and (current["location"], int(current["site"])) == (location, site)):
                where = f"{current['location']}[{current['site']}]"
                raise BackendError(f"{label} is already on the deck at {where}; use MoveLabwareRecord or RemoveLabware")
            if view is not None and label in view.labware:
                base_type = view.labware[label].get("type")
                if base_type and base_type != labware_type:
                    raise BackendError(f"{label} is a {base_type} on the base worktable, not a {labware_type}")
            if not on_deck:  # a rack refilled in place keeps its position
                self._check_position(view, entries, label, location, site)
            entry = {
                "type": labware_type,
                "location": location,
                "site": site,
                "base": base,
                "placed_by": placed_by,
                "placed_at": self._now(),
            }
            if lid:
                entry["lid"] = lid
            if tips is not None:
                entry["tips"] = tips
            entries[label] = entry
            self._prune(entries, label)
            return {"label": label, "before": before, "after": entries.get(label), "warnings": warnings}

        return self._change(command, args, fn)

    def place_tip_rack(self, label: str, tip_type: str, location: str, site: int, kind: str, placed_by: str) -> int:
        """PlaceLabware that also records the tip state ("full" or "as is"). A rack already on the deck at that
        position is taken as refilled in place."""
        if kind not in TIP_KINDS:
            raise BackendError(f"Kind must be one of {', '.join(repr(k) for k in TIP_KINDS)}")
        tips = {"kind": kind, "since": self._now()}
        return self.place(label, tip_type, location, site, "", placed_by, tips, "PlaceTipRack")

    def remove(self, label: str, removed_by: str = "") -> int:
        """Record that a labware was taken off the deck."""

        def fn(entries: dict) -> dict:
            before = entries.get(label)
            if before is not None:
                if before.get("location") is None:
                    raise BackendError(f"{label} is already recorded as taken off the deck")
                base = before.get("base")
            else:
                view = self._view()
                base = self._base_of(view, label)
                if base is None:
                    raise BackendError(self._unknown(label, view))
                before = {"type": view.labware[label].get("type", ""), **base}
            if base:
                entries[label] = {
                    "type": before.get("type", ""),
                    "location": None,
                    "site": None,
                    "base": base,
                    "removed_by": removed_by,
                    "removed_at": self._now(),
                }
            else:
                del entries[label]
            return {"label": label, "before": before, "after": entries.get(label)}

        return self._change("RemoveLabware", {"label": label, "by": removed_by}, fn)

    def _unknown(self, label: str, view) -> str:
        if view is None:
            return f"{label} is not in the deck state (and the base worktable could not be checked in this dry run)"
        return f"{label} is neither on the base worktable {view.worktable} nor in the deck state"

    def move(self, label: str, location: str, site: int, moved_by: str = "", command: str = "MoveLabwareRecord") -> int:
        """Record that a labware was moved by something other than the RGA (checked like PlaceLabware)."""
        site = int(site)

        def fn(entries: dict) -> dict:
            view = self._view()
            before = entries.get(label)
            if before is None:
                base = self._base_of(view, label)
                if base is None:
                    raise BackendError(self._unknown(label, view))
                entry = {"type": view.labware[label].get("type", ""), **base, "base": base}
            elif before.get("location") is None:
                raise BackendError(f"{label} is recorded as taken off the deck; use PlaceLabware")
            else:
                entry = dict(before)
            self._check_position(view, entries, label, location, site)
            entry.update(location=location, site=site, moved_by=moved_by, moved_at=self._now())
            entries[label] = entry
            self._prune(entries, label)
            return {"label": label, "before": before, "after": entries.get(label)}

        return self._change(command, {"label": label, "location": location, "site": site, "by": moved_by}, fn)

    def record_rga_move(
        self,
        label: str,
        location: str,
        site: int,
        base: dict | None = None,
        labware_type: str = "",
        session_labels=(),
        moved_by: str = "RGA",
    ) -> int | None:
        """Record a move the RGA has done (after it succeeded; never refused for a taken site). base and labware_type
        come from the tracker for its labware; otherwise the base worktable is looked up. Labware that exists only
        in the open run (added with Labware.AddLabware) is not recorded: None."""
        site = int(site)
        state = self.load()
        if label not in state["labware"] and base is None:
            if label in session_labels:
                return None
            view = self._view()
            base = self._base_of(view, label)
            if base is None:
                if view is None:  # dry run without definitions
                    logger.warning("Deck state: %s not recorded (base worktable unknown in this dry run)", label)
                    return None
                raise BackendError(self._unknown(label, view))
            labware_type = view.labware[label].get("type", "")

        def fn(entries: dict) -> dict:
            before = entries.get(label)
            entry = dict(before) if before is not None else {"type": labware_type, "base": base}
            warnings = []
            other = self._occupied(entries, None).get((location, site))
            if other and other != label:
                warnings.append(f"{location}[{site}] was recorded for {other}")
            entry.update(location=location, site=site, moved_by=moved_by, moved_at=self._now())
            entries[label] = entry
            self._prune(entries, label)
            return {"label": label, "before": before, "after": entries.get(label), "warnings": warnings}

        return self._change("RgaMove", {"label": label, "location": location, "site": site, "by": moved_by}, fn)

    def set_contents(self, label: str, wells: list[str], liquid: str, volumes: list[float]) -> int:
        """Record what a labware holds: one volume per well, or one volume for all. A volume of 0 empties the well."""
        wells = [w.strip().upper() for w in wells]
        if not wells or any(not WELL.fullmatch(w) for w in wells):
            raise BackendError("Wells must be names such as A1 or H12")
        if len(volumes) not in (1, len(wells)) or any(v < 0 for v in volumes):
            raise BackendError("Give one volume (ul, 0 or more) for all wells, or one per well")
        per_well = list(volumes) if len(volumes) == len(wells) else [volumes[0]] * len(wells)

        def fn(entries: dict) -> dict:
            before = entries.get(label)
            if before is None:
                view = self._view()
                base = self._base_of(view, label)
                if base is None:
                    raise BackendError(self._unknown(label, view))
                entry = {"type": view.labware[label].get("type", ""), **base, "base": base}
            elif before.get("location") is None:
                raise BackendError(f"{label} is recorded as taken off the deck")
            else:
                entry = copy.deepcopy(before)
            contents = entry.get("contents") or {}
            for well, volume in zip(wells, per_well, strict=True):
                if volume == 0:
                    contents.pop(well, None)
                else:
                    contents[well] = {"liquid": liquid, "volume_ul": volume}
            entry["contents"] = contents
            entries[label] = entry
            self._prune(entries, label)
            return {"label": label, "before": before, "after": entries.get(label)}

        args = {"label": label, "wells": wells, "liquid": liquid, "volumes": list(volumes)}
        return self._change("SetContents", args, fn)

    # ---- the start of a run
    def registration(self) -> tuple[list[tuple[str, str]], dict]:
        """The statements that bring FluentControl's record in line with the deck state at the start of a run, and
        what the record of the run start keeps (version, file, racks registered as full).

        First RemoveLabware for every base-worktable labware that was moved or taken off (and racks refilled at their
        base position), then AddLabware for everything on the deck that FluentControl would not have where it is,
        each in label order. Removing everything first keeps a site free for a labware moved onto the base position
        of another one. Nothing moves."""
        state = self.load()
        removes, adds, refills = [], [], []
        for label in sorted(state["labware"]):
            e = state["labware"][label]
            refill = (e.get("tips") or {}).get("kind") == "full" and not e["tips"].get("registered_at")
            if e.get("location") is None:
                if e.get("base"):
                    removes.append(label)
                continue
            if _at_base(e) and not refill:
                continue
            if e.get("base"):
                removes.append(label)
            adds.append(label)
            if refill:
                refills.append(label)
        entries = state["labware"]
        steps = [
            (f"RemoveLabware {label} (deck state, bookkeeping only)", remove_labware_xml(label)) for label in removes
        ]
        steps += [
            (
                f"AddLabware {label} at {_position(entries[label])} (deck state, bookkeeping only)",
                add_labware_xml(entries[label]["type"], label, entries[label]["location"], int(entries[label]["site"])),
            )
            for label in adds
        ]
        info = {
            "file": self.config.state_file,
            "base_worktable": state["base_worktable"],
            "version": state["version"],
            "removed": removes,
            "added": {label: entries[label]["type"] for label in adds},
            "refilled": refills,
        }
        return steps, info

    def registered(self, info: dict) -> None:
        """After the registration was sent: racks registered as full count as registered (FluentControl's own count
        of used tips is authoritative from then on)."""
        refills = info.get("refilled") or []
        if not refills:
            return

        def fn(entries: dict) -> dict:
            for label in refills:
                if label in entries and entries[label].get("tips"):
                    entries[label]["tips"]["registered_at"] = self._now()
            return {"labels": refills}

        self._change("RegisteredFull", {"labels": refills}, fn)

    # ---- labels an operation uses
    def check_labels(self, steps: list[tuple[str, str]], base_labels: set, session_labels=()) -> tuple[list, dict]:
        """Problems with the labware labels the steps use: a label that is neither on the base worktable nor in the
        deck state, or one recorded as taken off the deck (except in RemoveLabware). Labware added by an AddLabware
        of the same steps or in the open run is known."""
        state = self.load()
        entries = state["labware"]
        added = {m.strip() for _, xml in steps for m in re.findall(r"<LabwareLable>([^<]+)</LabwareLable>", xml)}
        problems = []
        for _, xml in steps:
            removing = "RemoveLabwareDataV1" in xml
            for label in extract_references(_unescape(xml))["labware"]:
                if label in added or label in session_labels or label.startswith("FCA Thru Deck Waste"):
                    continue
                e = entries.get(label)
                if e is not None:
                    if e.get("location") is None and not removing:
                        problems.append(
                            f"Labware '{label}' is recorded as taken off the deck (by {e.get('removed_by') or '?'}, "
                            f"{e.get('removed_at') or '?'})"
                        )
                    continue
                if label not in base_labels:
                    problems.append(
                        f"Labware '{label}' is neither on the base worktable {self.base_worktable} "
                        "nor in the deck state"
                    )
        return sorted(set(problems)), {"file": self.config.state_file, "version": state["version"]}

    # ---- views
    @staticmethod
    def _line(label: str, e: dict) -> str:
        notes = []
        if e.get("location") is None:
            text = f"{label}: {e.get('type', '')} taken off the deck"
            if e.get("removed_by"):
                notes.append(f"removed by {e['removed_by']}")
        else:
            text = f"{label}: {e.get('type', '')} at {_position(e)}"
            if e.get("lid"):
                notes.append(f"lid {e['lid']}")
            if e.get("placed_by"):
                notes.append(f"placed by {e['placed_by']}")
            if e.get("moved_by"):
                notes.append(f"moved by {e['moved_by']}")
        base = e.get("base")
        notes.append(f"base {base['location']}[{base['site']}]" if base else "not on the base worktable")
        if e.get("tips"):
            notes.append(f"tips {e['tips']['kind']}")
        if e.get("contents"):
            notes.append(f"{len(e['contents'])} wells with contents")
        return text + f" ({', '.join(notes)})"

    def layout(self) -> list[str]:
        """The base worktable and version, then one line per listed labware."""
        state = self.load()
        lines = [f"base worktable {state['base_worktable']}, version {state['version']}"]
        lines += [self._line(label, e) for label, e in sorted(state["labware"].items())]
        return lines

    def tip_racks(self) -> list[str]:
        """Every rack recorded with a tip state: tip type, position and state."""
        out = []
        for label, e in sorted(self.load()["labware"].items()):
            tips = e.get("tips")
            if not tips:
                continue
            where = "taken off the deck" if e.get("location") is None else f"at {_position(e)}"
            state = f"{tips['kind']} since {tips.get('since', '?')}"
            if tips["kind"] == "full":
                state += (
                    f", registered at run start {tips['registered_at']}"
                    if tips.get("registered_at")
                    else ", registered at the next run start"
                )
            out.append(f"{label}: {e.get('type', '')} {where} ({state})")
        return out

    def positions(self) -> dict[str, list]:
        """Labware on the deck away from its base position, or not on the base worktable: label -> [location, site]."""
        return {
            label: [e["location"], int(e["site"])]
            for label, e in self.load()["labware"].items()
            if e.get("location") is not None and not _at_base(e)
        }

    def entry(self, label: str) -> dict | None:
        return self.load()["labware"].get(label)
