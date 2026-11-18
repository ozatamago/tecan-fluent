"""Feature that keeps the deck state: what people and other robots put on, take off or move on the deck
(io/fluent/deck/state.py)."""

import asyncio

from unitelabs.cdk import sila

from ...io.fluent.deck.state import DeckState
from ...io.fluentcontrol.backend import BackendError, FluentControlBackend


class DeckCommandFailed(Exception):
    """The deck state was not changed. The description says why (site taken, unknown type or location, run open)."""


class Deck(sila.Feature):
    """
    What is on the deck, kept as data that people and other robots can change. Nothing here moves the instrument.

    The deck state lists how the deck differs from the base worktable (the worktable FluentControl's OFML_ApiHost
    uses): labware put on the deck, labware of the base worktable moved or taken off, the tips of racks put in, and
    what the labware contains. At the start of every run (RunControl.StartRun, and every command that opens a run
    of its own) FluentControl's record is brought in line with it by RemoveLabware / AddLabware (bookkeeping only),
    and the RGA commands update it after each move. Commands that use a labware that is neither on the base worktable
    nor in the deck state are refused before anything is sent.

    Record changes while hands-off is held (Fluent - Hands Off) and no run is open: an open run already has its
    layout. Every change increases the version and is recorded on the Fluent PC (folder deck of the OFML records).
    CheckRgaMoves checks a planned sequence of RGA transfers against the deck for collisions.
    """

    def __init__(self, backend: FluentControlBackend, deck: DeckState | None):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.fluent",
            identifier="Deck",
            name="Fluent - Deck",
            version="1.0",
        )
        self.backend = backend
        self.deck = deck
        """None when no deck state is configured (setting deck.state_file): the commands are refused."""

    def _need(self, change_layout: bool = True) -> DeckState:
        if self.deck is None:
            raise DeckCommandFailed("No deck state is configured (setting deck.state_file)")
        if change_layout:
            if self.backend.run_open:
                raise DeckCommandFailed(
                    f"A run is open (since {self.backend.run_started}) and already has its layout; "
                    "record the change after RunControl.EndRun"
                )
            if self.backend.busy:
                raise DeckCommandFailed(f"A command is being sent ({self.backend.current_operation})")
            other = self.backend.other_server()
            if other and not other.startswith("hands-off by"):
                raise DeckCommandFailed(f"FluentControl is in use by another server on the Fluent PC ({other})")
        return self.deck

    async def _call(self, fn, *args):
        try:
            return await asyncio.to_thread(fn, *args)
        except BackendError as exc:
            raise DeckCommandFailed(str(exc)) from None

    @sila.UnobservableProperty(errors=[DeckCommandFailed])
    async def get_layout(self) -> list[str]:
        """The deck state: first the base worktable and the version, then one line per labware that differs from the
        base worktable ("label: type at location[site] (lid ..., placed by ..., base ...)")."""
        if self.deck is None:
            return ["no deck state configured (setting deck.state_file)"]
        return await self._call(self.deck.layout)

    @sila.UnobservableProperty(errors=[DeckCommandFailed])
    async def get_tip_racks(self) -> list[str]:
        """Every tip rack recorded with PlaceTipRack or SetTipRackNextWell: tip type, position and recorded state
        ("full" racks are registered at the next run start, after which FluentControl's own count of used tips is
        authoritative; "partial" racks get the well of their next tip at every run start; racks away from their base
        position that are "used" or "as is", and empty racks, are marked not usable)."""
        if self.deck is None:
            return []
        return await self._call(self.deck.tip_racks)

    @sila.UnobservableCommand(errors=[DeckCommandFailed])
    async def check_rga_moves(self, moves: list[str]) -> list[str]:
        """
        Check a planned sequence of RGA transfers for collisions, against the deck as it is now. Moves nothing and
        needs no FluentControl run (only the base worktable and the deck state on the Fluent PC).

        Each move is checked as every RGA command checks it before it is sent: any part of the RGA (fingers, gripper
        blocks, rotator, pillar) and the carried labware must stay at least the margin (setting
        fluent.rga_clearance.margin_mm, 5 mm) away from everything on the deck while the RGA goes straight down to the
        grip height and back up to the safe height, at the source and at the destination. FluentControl checks only
        the travel at safe height, not these descents. Each move is applied to a copy of the deck before the next one
        is checked, so a whole run can be checked before it is started.

        Args:
          Moves: One move per entry, "label: source -> destination" or "label -> destination" (from where it is
            now), e.g. "PlateB_Lid[001]: Nest7mm_Pos[2] -> HotelMP_Pos[3]". Source and destination are positions such
            as Nest7mm_Pos[2]; the destination can also be "base" or "lid of <plate>". For labware not on the deck
            give its type: "Plate_A[001] (96 Well Flat_Custom): Nest7mm_Pos[1] -> Regrip_Pos[1]".

        Returns:
          Results: One line per move: "OK" with the smallest gap and where it occurs, "REFUSED" with the RGA part,
            the obstacle, the site and the gap, or "NOT CHECKED" with what the geometry table lacks.
        """
        results = await self._call(self.backend.check_rga_moves, list(moves))
        out = []
        for i, r in enumerate(results, 1):
            line = f"{i}. {r.summary()}"
            if r.notes:
                line += f" (note: {'; '.join(r.notes)})"
            out.append(line)
        return out

    @sila.UnobservableCommand(errors=[DeckCommandFailed])
    async def place_labware(
        self, label: str, labware_type: str, location: str, site: int, lid: str, placed_by: str
    ) -> int:
        """
        Record that a labware was put on the deck (by a person or a robot). Moves nothing. Refused if the site is
        taken, the labware type is not defined in FluentControl, or the location or site is not on the base
        worktable.

        Args:
          Label: Name of the labware, e.g. "Plate_A[001]". FluentControl knows it by this name from the next run on.
          LabwareType: FluentControl labware type, e.g. "96 Well Flat_Custom".
          Location: Location name on the base worktable, e.g. "Nest7mm_Pos".
          Site: Site number (from 1).
          Lid: Name of the lid on it, or empty for none (recorded only).
          PlacedBy: Who put it there, e.g. "Franka" or "a person".

        Returns:
          Version: The version of the deck state after the change.
        """
        deck = self._need()
        return await self._call(deck.place, label, labware_type, location, site, lid, placed_by)

    @sila.UnobservableCommand(errors=[DeckCommandFailed])
    async def remove_labware(self, label: str, removed_by: str) -> int:
        """
        Record that a labware was taken off the deck. Moves nothing.

        Args:
          Label: Name of the labware, e.g. "Plate_A[001]".
          RemovedBy: Who took it off, e.g. "Kachaka".

        Returns:
          Version: The version of the deck state after the change.
        """
        deck = self._need()
        return await self._call(deck.remove, label, removed_by)

    @sila.UnobservableCommand(errors=[DeckCommandFailed])
    async def move_labware_record(self, label: str, location: str, site: int, moved_by: str) -> int:
        """
        Record that a labware was moved by something other than the RGA (a person or another robot). Moves nothing.

        Args:
          Label: Name of the labware, e.g. "96 Well Flat_Custom[001]".
          Location: Location name where it is now, e.g. "Nest7mm_Pos".
          Site: Site number (from 1).
          MovedBy: Who moved it, e.g. "a person".

        Returns:
          Version: The version of the deck state after the change.
        """
        deck = self._need()
        return await self._call(deck.move, label, location, site, moved_by)

    @sila.UnobservableCommand(errors=[DeckCommandFailed])
    async def set_contents(self, label: str, wells: list[str], liquid: str, volumes: list[float]) -> int:
        """
        Record what a labware holds (used later for planning and checks). Moves nothing; also allowed during a run.

        Args:
          Label: Name of the labware, e.g. "Plate_A[001]".
          Wells: Wells, e.g. ["A1", "B1"].
          Liquid: What is in them, e.g. "water".
          Volumes: Volume in ul, one per well or one for all. 0 empties the well.

        Returns:
          Version: The version of the deck state after the change.
        """
        deck = self._need(change_layout=False)
        return await self._call(deck.set_contents, label, wells, liquid, volumes)

    @sila.UnobservableCommand(errors=[DeckCommandFailed])
    async def place_tip_rack(
        self, label: str, tip_type: str, location: str, site: int, kind: str, placed_by: str
    ) -> int:
        """
        Record that a tip rack was put on the deck, with its tips. Moves nothing. Checked like PlaceLabware; a rack
        already on the deck at that position counts as refilled in place.

        A "full" rack is registered at the next run start with RemoveLabware / AddLabware, so FluentControl sees a
        full rack. At its base position FluentControl then keeps its own count of used tips. Away from its base
        position a full rack is registered once only; the tips LiquidHandling takes from it in that run are read from
        FluentControl's log and the rack becomes "partial". A partial rack (Kind is the well of its next tip, e.g.
        "C1") is registered at every run start and then gets FluentControl's "Set Available Tips" for that well
        (FluentControl uses tips column-wise: A1, B1, ..., H1, A2, ...). That statement marks only that one well as
        available, so LiquidHandling.GetTips naming the rack sends it again before every GetTips (one channel at a
        time). A rack whose tips taken are unknown counts
        as used, and away from its base position commands that use it are refused until it is recorded again or
        taken off; a rack put back "as is" away from its base position is refused the same way.

        Args:
          Label: Name of the rack, e.g. "FCA_ 200ul SBS[001]".
          TipType: FluentControl tip type, e.g. "FCA, 200ul SBS".
          Location: Location name, e.g. "Nest7mm_Pos".
          Site: Site number (from 1).
          Kind: "full" (a fresh rack), "as is" (a rack taken out earlier and put back), or the well of the next tip
            of a partly used rack, e.g. "C1" (A1 and B1 are gone).
          PlacedBy: Who put it there.

        Returns:
          Version: The version of the deck state after the change.
        """
        deck = self._need()
        return await self._call(deck.place_tip_rack, label, tip_type, location, site, kind, placed_by)

    @sila.UnobservableCommand(errors=[DeckCommandFailed])
    async def set_tip_rack_next_well(self, label: str, well: str, set_by: str) -> int:
        """
        Record the well of the next tip of a tip rack on the deck (a partly used rack). Moves nothing. Works for a
        rack of the base worktable at its base position too; FluentControl's own count is overridden from then on.

        At every run start, after the registration, FluentControl gets "Set Available Tips" for this well, and
        LiquidHandling.GetTips naming the rack sends it again right before every GetTips (the statement marks only that
        one well as available, so one channel at a time). The tips LiquidHandling takes from the rack (GetTips, the
        Smart Commands, worklists) move the recorded well on, read from FluentControl's log. FluentControl uses tips
        column-wise (A1, B1, ..., H1, A2, ...), so "C1" means A1 and B1 are gone. Tips taken any other way (a GUI
        script, raw XML) are not seen: record the well again. To give a rack at its base position back to
        FluentControl's own count, record it with PlaceTipRack.

        Args:
          Label: Name of the rack, e.g. "FCA_ 1000ul SBS[002]".
          Well: Well of the next tip, e.g. "C1".
          SetBy: Who counted the tips, e.g. "a person".

        Returns:
          Version: The version of the deck state after the change.
        """
        deck = self._need()
        return await self._call(deck.set_tip_rack_next_well, label, well, set_by)
