"""Feature that moves labware with the RGA (plate gripper). Where moved labware is: io/labware_tracker.py."""

from unitelabs.cdk import sila

from ..io.fluent_backend import BackendError, FluentOdtcBackend
from ..io.labware_tracker import LabwareTracker
from .infinite import _with_progress


class PlateTransferFailed(Exception):
    """The labware could not be moved. The description explains why (not registered, FluentControl busy, ...)."""


class PlateTransfer(sila.Feature):
    """
    Move labware with the RGA (plate gripper) of the Fluent 780.

    Only labware listed in the connector configuration can be moved. The connector remembers where it put each
    labware, so a plate can be moved in one command and brought back in a later one: FluentControl forgets labware
    positions between runs, and the connector re-registers the plate at its actual position before moving it.
    If someone moves a plate by hand, tell the connector with RecordLabwarePosition before the next move.
    """

    def __init__(self, backend: FluentOdtcBackend, tracker: LabwareTracker):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.fluent.gripper",
            identifier="PlateTransfer",
            name="RGA Gripper - Move & Return Plate",
            version="1.0",
        )
        self.backend = backend
        self.tracker = tracker

    async def _move(self, labware: str, location: str, site: int, status: sila.Status) -> str:
        try:
            steps = self.tracker.move_steps(labware, location, site)
            await _with_progress(
                status,
                len(steps),
                lambda report: self.backend.run_steps(steps, report, f"RGA: {labware} -> {location}[{site}]"),
            )
        except BackendError as exc:
            raise PlateTransferFailed(str(exc)) from None
        self.tracker.record(labware, location, site)
        return f"{location}[{site}]"

    @sila.UnobservableProperty()
    async def get_labware_positions(self) -> list[str]:
        """Movable labware and where the connector believes each one is ("name: location[site] (base ...)")."""
        out = []
        for name in self.tracker.config.labware:
            loc, site = self.tracker.where(name)
            bloc, bsite = self.tracker.base(name)
            note = "at base" if not self.tracker.moved_away(name) else f"base {bloc}[{bsite}]"
            out.append(f"{name}: {loc}[{site}] ({note})")
        return out

    @sila.ObservableCommand(errors=[PlateTransferFailed])
    async def move_labware(self, labware: str, location: str, site: int, *, status: sila.Status) -> str:
        """
        Move labware to a worktable position with the RGA (one FluentControl run).

        Args:
          Labware: Labware name, e.g. "96 Well Flat_Custom[001]". See LabwarePositions.
          Location: Target location name, e.g. "Regrip_Pos" (the regrip position used before the reader).
          Site: Target site number, e.g. 1.

        Returns:
          NewPosition: Where the labware is now, e.g. "Regrip_Pos[1]".
        """
        return await self._move(labware, location, site, status)

    @sila.ObservableCommand(errors=[PlateTransferFailed])
    async def return_labware(self, labware: str, *, status: sila.Status) -> str:
        """
        Bring labware back to its base position (its position in the worktable definition) with the RGA.

        Args:
          Labware: Labware name, e.g. "96 Well Flat_Custom[001]".

        Returns:
          NewPosition: The base position, e.g. "Nest7mm_Pos[6]".
        """
        try:
            location, site = self.tracker.base(labware)
        except BackendError as exc:
            raise PlateTransferFailed(str(exc)) from None
        return await self._move(labware, location, site, status)

    @sila.UnobservableCommand(errors=[PlateTransferFailed])
    async def record_labware_position(self, labware: str, location: str, site: int) -> str:
        """
        Tell the connector where a labware really is, without moving anything (e.g. after moving it by hand).

        Args:
          Labware: Labware name.
          Location: Location name where the labware is now.
          Site: Site number.

        Returns:
          NewPosition: The recorded position.
        """
        try:
            self.tracker.spec(labware)
        except BackendError as exc:
            raise PlateTransferFailed(str(exc)) from None
        self.tracker.record(labware, location, site)
        return f"{location}[{site}]"
