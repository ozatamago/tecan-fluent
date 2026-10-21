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
        """Every tip rack recorded with PlaceTipRack: tip type, position and recorded state ("full" racks are
        registered at the next run start, after which FluentControl's own count of used tips is authoritative)."""
        if self.deck is None:
            return []
        return await self._call(self.deck.tip_racks)

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
        full rack. Whether FluentControl keeps that across later runs is not confirmed on the instrument yet:
        GetTips keeps its timeout.

        Args:
          Label: Name of the rack, e.g. "FCA_ 200ul SBS[001]".
          TipType: FluentControl tip type, e.g. "FCA, 200ul SBS".
          Location: Location name, e.g. "Nest7mm_Pos".
          Site: Site number (from 1).
          Kind: "full" (a fresh rack) or "as is" (a rack taken out earlier and put back).
          PlacedBy: Who put it there.

        Returns:
          Version: The version of the deck state after the change.
        """
        deck = self._need()
        return await self._call(deck.place_tip_rack, label, tip_type, location, site, kind, placed_by)
