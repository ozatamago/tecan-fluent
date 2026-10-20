"""The plate tray of the Tecan Infinite 200 PRO."""

from unitelabs.cdk import sila

from ...io.fluentcontrol.errors import BackendError
from ...io.fluentcontrol.progress import with_progress
from ...io.infinite.reader import FluentInfiniteReader  # the PyLabRobot backend has the same methods
from .errors import ReaderOperationFailed


class Tray(sila.Feature):
    """
    Open and close the plate tray of the Tecan Infinite 200 PRO. Make sure nothing is in the tray's way.

    The reader is driven through Tecan FluentControl (Magellan driver). Each command is one short FluentControl run.
    """

    def __init__(self, reader: FluentInfiniteReader):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.infinite",
            identifier="Tray",
            name="Infinite - Tray",
            version="1.0",
        )
        self.reader = reader

    async def _tray(self, fn, status: sila.Status) -> None:
        try:
            await with_progress(status, 1, fn)
        except BackendError as exc:
            raise ReaderOperationFailed(str(exc)) from None

    @sila.ObservableCommand(errors=[ReaderOperationFailed])
    async def open_tray(self, *, status: sila.Status) -> None:
        """Move the tray out of the reader."""
        await self._tray(self.reader.open_tray, status)

    @sila.ObservableCommand(errors=[ReaderOperationFailed])
    async def close_tray(self, *, status: sila.Status) -> None:
        """Move the tray into the reader."""
        await self._tray(self.reader.close_tray, status)
