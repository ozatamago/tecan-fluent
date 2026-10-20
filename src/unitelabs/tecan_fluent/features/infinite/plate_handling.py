"""Measuring a plate from the Fluent worktable: the RGA brings it into the Infinite 200 PRO and back."""

from unitelabs.cdk import sila

from ...io.fluentcontrol.errors import BackendError
from ...io.fluentcontrol.progress import with_progress
from ...io.infinite.reader import FluentInfiniteReader  # the PyLabRobot backend has the same methods
from .absorbance import MeasurementResult, _result
from .errors import ReaderOperationFailed


class PlateHandling(sila.Feature):
    """
    Measure a plate from the Fluent worktable: the RGA brings it into the Infinite 200 PRO, it is measured, and the
    RGA puts it back - all within one FluentControl run (FluentControl forgets labware positions between runs).

    Flat-bottom plates only: PCR plates cannot be regripped for the reader with the current Fluent configuration.
    The plate must not have a lid. The source site must be free in FluentControl's worktable memory.
    """

    def __init__(self, reader: FluentInfiniteReader, tracker=None):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.infinite",
            identifier="PlateHandling",
            name="Infinite - Plate In / Out (RGA)",
            version="1.0",
        )
        self.reader = reader
        self.tracker = tracker
        """The LabwareTracker shared with PlateTransfer (if any), so a plate that has been moved away is not fetched
        from its original position."""

    @sila.ObservableCommand(errors=[ReaderOperationFailed])
    async def measure_plate(
        self, labware_type: str, location: str, site: int, method: str, *, status: sila.Status
    ) -> MeasurementResult:
        """
        Bring a plate from the worktable into the reader, measure it, and put it back.

        Args:
          LabwareType: FluentControl labware type of the plate, e.g. "96 Well Flat_Custom".
          Location: Worktable location (carrier location name) where the plate is, e.g. "Nest7mm_Pos".
          Site: Site number at that location, e.g. 7.
          Method: Magellan method file, e.g. "OFML_Abs405.mth". See Absorbance.Methods.

        Returns:
          Result: The measured values and the result file.
        """
        try:
            await self.reader.check_method(method)
            name = self.reader._measure_name()
            steps = self.reader.load_measure_unload_steps(labware_type, location, site, method, name)
            path, asc = await with_progress(status, len(steps), lambda report: self.reader.run(steps, name, report))
        except BackendError as exc:
            raise ReaderOperationFailed(str(exc)) from None
        return _result(method, path, asc)

    @sila.ObservableCommand(errors=[ReaderOperationFailed])
    async def measure_worktable_plate(self, labware: str, method: str, *, status: sila.Status) -> MeasurementResult:
        """
        Bring a plate that is registered on the FluentControl worktable (by its name) into the reader, measure it,
        and put it back to its base position - all within one FluentControl run.

        Args:
          Labware: Labware name on the worktable, e.g. "96 Well Flat_Custom[001]".
          Method: Magellan method file, e.g. "OFML_Abs405.mth". See Absorbance.Methods.

        Returns:
          Result: The measured values and the result file.
        """
        try:
            if self.tracker is not None and labware in self.tracker.positions:
                loc, site = self.tracker.where(labware)
                raise BackendError(
                    f"{labware} is currently at {loc}[{site}] (moved by PlateTransfer). Use ReturnLabware first"
                )
            await self.reader.check_method(method)
            name = self.reader._measure_name()
            steps = self.reader.worktable_plate_steps(labware, method, name)
            path, asc = await with_progress(status, len(steps), lambda report: self.reader.run(steps, name, report))
        except BackendError as exc:
            raise ReaderOperationFailed(str(exc)) from None
        return _result(method, path, asc)
