"""The record of where labware moved by the RGA (plate gripper) is.

FluentControl resets labware positions to their worktable defaults at the start of every run (confirmed 2026-08-13).
To move and return a plate in separate runs, this connector remembers the current position and, at the start of the
next run, aligns FluentControl's record with the actual position via RemoveLabware -> AddLabware before moving
(the same approach as the 10-09 recovery).

The positions are kept on the Fluent PC (``C:\\Users\\Tecan\\OFML\\state\\labware_positions.json``) and read
before every use, so they survive a restart and stay correct whichever computer runs the connector. If the Fluent PC
cannot be reached, moves are refused rather than guessed. In a dry run, moves are remembered in memory only.

With a deck state (setting deck.state_file, io/fluent/deck/state.py) the tracker is a view on it: positions are read
from and recorded in the deck state, which takes over labware_positions.json once, and the backend brings
FluentControl's record in line with it at the start of every run, so a move needs no RemoveLabware / AddLabware of
its own.
"""

import dataclasses
import json
import os
import pathlib
import re

from unitelabs.cdk.config import Config

from ...fluentcontrol.definitions import DefinitionCheckFailed, FluentPc
from ...fluentcontrol.errors import BackendError
from .statements import add_labware_xml, remove_labware_xml, rga_xml


@dataclasses.dataclass
class PlateTransferConfig(Config):
    """Labware the RGA may move, and its base position (its default position on the worktable)."""

    labware: dict = dataclasses.field(
        default_factory=lambda: {
            # 2026-10-09 protocol: 96 Well Flat_Custom[001] sits on 7mm Nest_Custom[006] (site 6 of Nest7mm_Pos)
            "96 Well Flat_Custom[001]": {"type": "96 Well Flat_Custom", "base_location": "Nest7mm_Pos", "base_site": 6},
        }
    )
    positions_file: str = r"C:\Users\Tecan\OFML\state\labware_positions.json"
    """File holding the current positions of moved labware. A Windows path (C:\\...) is on the Fluent PC;
    any other path is on the computer running the connector (used by the tests)."""


class LabwareTracker:
    def __init__(self, config: PlateTransferConfig, pc: FluentPc | None = None, persist: bool = True, deck=None):
        self.config = config
        self.deck = deck
        """The DeckState this tracker is a view on (None: positions_file as before)."""
        # A Windows path is on the Fluent PC: read over SSH from another computer, directly on the Fluent PC itself
        self.remote = bool(re.match(r"^[A-Za-z]:\\", config.positions_file)) and os.name != "nt"
        self.pc = pc
        self.persist = persist
        self._dry: dict[str, list] | None = None
        """Positions changed by dry-run moves (never written anywhere)."""

    def _load(self) -> dict[str, list]:
        try:
            if self.remote:
                if self.pc is None:
                    raise BackendError("No connection to the Fluent PC configured for labware positions")
                text = self.pc.read_file(self.config.positions_file)
            else:
                path = pathlib.Path(self.config.positions_file).expanduser()
                text = path.read_text(encoding="utf-8") if path.exists() else None
        except DefinitionCheckFailed as exc:
            raise BackendError(f"Cannot read the labware positions on the Fluent PC: {exc}") from None
        return json.loads(text) if text and text.strip() else {}

    def _save(self, positions: dict[str, list]) -> None:
        text = json.dumps(positions, ensure_ascii=False, indent=1)
        if self.remote:
            try:
                self.pc.write_file(self.config.positions_file, text)
            except DefinitionCheckFailed as exc:
                raise BackendError(f"Cannot save the labware positions on the Fluent PC: {exc}") from None
        else:
            path = pathlib.Path(self.config.positions_file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    @property
    def positions(self) -> dict[str, list]:
        """Labware that is away from its base position: name -> [location, site]. Read fresh on every use.
        With a deck state, this includes every labware on the deck away from its base (or not on the worktable)."""
        if self.deck is not None:
            return self.deck.positions()
        return dict(self._dry) if self._dry is not None else self._load()

    def spec(self, labware: str) -> dict:
        if labware not in self.config.labware:
            raise BackendError(f"{labware} is not registered as movable labware (setting plates.labware)")
        return self.config.labware[labware]

    def base(self, labware: str) -> tuple[str, int]:
        s = self.spec(labware)
        return s["base_location"], int(s["base_site"])

    def where(self, labware: str) -> tuple[str, int]:
        """Current position as known to this connector; the base position if it has not been moved."""
        if self.deck is not None:
            entry = self.deck.entry(labware)
            if entry is not None and entry.get("location") is None:
                raise BackendError(f"{labware} is recorded as taken off the deck (Deck.RemoveLabware)")
        if labware in self.positions:
            loc, site = self.positions[labware]
            return loc, int(site)
        return self.base(labware)

    def moved_away(self, labware: str) -> bool:
        return labware in self.positions

    def record(self, labware: str, location: str, site: int, by: str = "RGA") -> None:
        if self.deck is not None:
            bloc, bsite = self.base(labware)
            base = {"location": bloc, "site": bsite}
            self.deck.record_rga_move(labware, location, site, base, self.spec(labware)["type"], moved_by=by)
            return
        positions = self.positions
        if (location, int(site)) == self.base(labware):
            positions.pop(labware, None)
        else:
            positions[labware] = [location, int(site)]
        if self.persist:
            self._save(positions)
        else:
            self._dry = positions

    def move_steps(self, labware: str, location: str, site: int) -> list[tuple[str, str]]:
        """Commands to move from the current position to (location, site); if not at base, first fix FluentControl's
        record."""
        spec = self.spec(labware)
        steps: list[tuple[str, str]] = []
        if self.deck is None and self.moved_away(labware):  # with a deck state, registered at the start of the run
            loc, s = self.where(labware)
            steps += [
                (f"RemoveLabware {labware} (bookkeeping only)", remove_labware_xml(labware)),
                (
                    f"AddLabware {labware} at {loc}[{s}] (bookkeeping only)",
                    add_labware_xml(spec["type"], labware, loc, s),
                ),
            ]
        steps.append((f"RGA {labware} -> {location}[{site}]", rga_xml(labware, location, str(site), fixed_site=True)))
        return steps
