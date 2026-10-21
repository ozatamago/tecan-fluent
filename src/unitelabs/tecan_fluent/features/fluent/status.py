from unitelabs.cdk import sila

from ...io.fluentcontrol.backend import BackendError, FluentControlBackend
from ..odtc.errors import OdtcOperationFailed


class Status(sila.Feature):
    """
    Whether the connector can take a command now. Reading these properties never moves or heats anything.

    The devices are driven through Tecan FluentControl, so a command can only start while FluentControl is idle
    (EditMode or RunModeRunFinished), no FluentControl dialog is waiting, and this connector is not already
    running another operation (on any device).
    """

    def __init__(self, backend: FluentControlBackend):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.fluent",
            identifier="Status",
            name="Fluent - Status",
            version="1.0",
        )
        self.backend = backend

    @sila.UnobservableProperty()
    async def get_busy(self) -> bool:
        """True while this connector is sending something to FluentControl (any device: ODTC, Infinite, ...)."""
        return self.backend.busy

    @sila.UnobservableProperty()
    async def get_current_operation(self) -> str:
        """What this connector is doing now, e.g. "ODTC: SiLA-ODTC_ExecuteMethod ini95", or "another server: ..." while
        another server on the Fluent PC uses FluentControl. Empty when idle."""
        other = self.backend.other_server()
        # hands-off held by this server shows as itself ("hands-off by ..."); held by another, as "another server: ..."
        return (
            self.backend.current_operation
            or self.backend.hands_off_text
            or (f"another server: {other}" if other else "")
        )

    @sila.UnobservableProperty(errors=[OdtcOperationFailed])
    async def get_fluent_control_state(self) -> str:
        """State of FluentControl, e.g. "EditMode", "RunModeRunning", "RunModeRunFinished"."""
        try:
            return (await self.backend.fluent_status())[0]
        except BackendError as exc:
            raise OdtcOperationFailed(str(exc)) from None

    @sila.UnobservableProperty(errors=[OdtcOperationFailed])
    async def get_active_dialogs(self) -> list[str]:
        """FluentControl dialogs waiting for an answer ("identifier: text"). Empty when none."""
        try:
            return (await self.backend.fluent_status())[1]
        except BackendError as exc:
            raise OdtcOperationFailed(str(exc)) from None

    @sila.UnobservableProperty(errors=[OdtcOperationFailed])
    async def get_ready(self) -> bool:
        """True when a command can start now (FluentControl idle, no dialog, neither this connector nor another server
        on the Fluent PC busy)."""
        if self.backend.busy or self.backend.hands_off_text or self.backend.other_server():
            return False
        try:
            state, dialogs = await self.backend.fluent_status()
        except BackendError as exc:
            raise OdtcOperationFailed(str(exc)) from None
        # an empty "Unused ID" dialog stays after FluentControl restarts and does not block a run
        blocking = [d for d in dialogs if d.split(":", 1)[-1].strip()]
        return state in {"EditMode", "RunModeRunFinished"} and not blocking
