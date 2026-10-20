"""Measuring the plate in the Tecan Infinite 200 PRO, and the measurement result (shared with PlateHandling and the
ColorMix demo)."""

import dataclasses

from unitelabs.cdk import sila

from ...io.fluentcontrol.errors import BackendError
from ...io.fluentcontrol.progress import with_progress
from ...io.infinite.reader import FluentInfiniteReader  # the PyLabRobot backend has the same methods
from .errors import ReaderOperationFailed


@dataclasses.dataclass
class WellValue(sila.CustomDataType):
    """
    One measured value.

    Args:
      Label: Measurement label as defined in the Magellan method (e.g. "Label1"; one per wavelength).
      Well: Well name, "A1" to "H12".
      Value: Measured value (absorbance in OD for absorbance methods). NaN when the reader reported no number.
    """

    label: str
    well: str
    value: float


@dataclasses.dataclass
class MeasurementResult(sila.CustomDataType):
    """
    Result of one measurement.

    Args:
      Method: Magellan method file used for the measurement.
      Labels: Measurement labels in the order they appear in the result file.
      Values: All measured values (labels x 96 wells).
      ResultFile: Path of the ASC result file on the Fluent PC (empty in dry-run mode).
      Metadata: Lines after the values in the result file (date, instrument, plate, wavelengths, ...).
    """

    method: str
    labels: list[str]
    values: list[WellValue]
    result_file: str
    metadata: list[str]


def _result(method: str, path: str, asc) -> MeasurementResult:
    if asc is None:
        return MeasurementResult(method=method, labels=[], values=[], result_file="", metadata=[])
    values = [
        WellValue(label=lbl, well=w, value=v)
        for lbl, grid in zip(asc.labels, asc.values, strict=False)
        for w, v in grid.items()
    ]
    return MeasurementResult(method=method, labels=asc.labels, values=values, result_file=path, metadata=asc.metadata)


class Absorbance(sila.Feature):
    """
    Measure the plate that is already in the Tecan Infinite 200 PRO.

    The same feature is served by two kinds of servers:
    - Fluent 780 reader (through FluentControl and Magellan): MeasureLoadedPlate runs a Magellan method file;
      ReadAbsorbance works for the wavelengths configured with a method file.
    - Stand-alone reader (USB, PyLabRobot): ReadAbsorbance takes any wavelength; MeasureLoadedPlate is not
      available (no Magellan), and Methods is empty.
    """

    def __init__(self, reader: FluentInfiniteReader):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.infinite",
            identifier="Absorbance",
            name="Infinite - Absorbance",
            version="1.0",
        )
        self.reader = reader

    @sila.UnobservableProperty(errors=[ReaderOperationFailed])
    async def get_methods(self) -> list[str]:
        """Magellan method files (.mth) available on the Fluent PC, e.g. "Abs600.mth"."""
        try:
            return await self.reader.list_methods()
        except BackendError as exc:
            raise ReaderOperationFailed(str(exc)) from None

    @sila.ObservableCommand(errors=[ReaderOperationFailed])
    async def measure_loaded_plate(self, method: str, *, status: sila.Status) -> MeasurementResult:
        """
        Measure the plate that is in the reader now. The tray must be closed with the plate inside.

        Args:
          Method: Magellan method file, e.g. "OFML_Abs405.mth". See the Methods property. Note that "Abs600.mth"
            has 37 degC temperature control switched on.

        Returns:
          Result: The measured values and the result file.
        """
        try:
            path, asc = await with_progress(status, 1, lambda report: self.reader.measure_loaded(method, report))
        except BackendError as exc:
            raise ReaderOperationFailed(str(exc)) from None
        return _result(method, path, asc)

    @sila.ObservableCommand(errors=[ReaderOperationFailed])
    async def read_absorbance(self, wavelength: int, *, status: sila.Status) -> MeasurementResult:
        """
        Read the absorbance of the plate that is in the reader now, at one wavelength, for all 96 wells.
        The tray must be closed with the plate inside.

        Args:
          Wavelength: Wavelength in nm (230 to 1000).

        Returns:
          Result: The measured OD values, one label named like "600nm".
        """
        try:
            path, asc = await with_progress(status, 1, lambda report: self.reader.read_absorbance(wavelength, report))
        except BackendError as exc:
            raise ReaderOperationFailed(str(exc)) from None
        return _result(f"{wavelength}nm", path, asc)
