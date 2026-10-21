"""Feature that keeps the Fluent still while another robot works on the deck (io/fluentcontrol/hands_off.py)."""

from unitelabs.cdk import sila

from ...io.fluentcontrol.errors import BackendError
from ...io.fluentcontrol.hands_off import HandsOff as HandsOffGuard


class HandsOffFailed(Exception):
    """Hands-off could not be taken or released. The description says why."""


class HandsOff(sila.Feature):
    """
    Keep the Fluent still while another robot (or a person) works on the deck. Nothing here moves the instrument.

    Begin takes the FluentControl lock shared by every server on the Fluent PC on behalf of the robot: until End,
    every server refuses FluentControl commands with "hands-off by <Who> (<Reason>, since ...)", and Fluent - Status
    shows it (Ready is false). Begin is refused while a run is open or a command is being sent. After MaxMinutes
    hands-off is released by itself, with a warning in the log and the records, so a robot that stopped answering
    does not block the Fluent forever.

    Change the deck only while hands-off is held, and record the changes with Fluent - Deck (PlaceLabware,
    RemoveLabware, MoveLabwareRecord), which may be called while it is held.
    """

    def __init__(self, guard: HandsOffGuard):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.fluent",
            identifier="HandsOff",
            name="Fluent - Hands Off",
            version="1.0",
        )
        self.guard = guard

    @sila.UnobservableCommand(errors=[HandsOffFailed])
    async def begin(self, who: str, reason: str, max_minutes: int) -> str:
        """
        Keep the Fluent still on behalf of another robot or a person. Moves nothing.

        Args:
          Who: Who works on the deck, e.g. "Franka" or "Kachaka".
          Reason: What it does, e.g. "puts a plate on Nest7mm_Pos[1]".
          MaxMinutes: After this many minutes hands-off is released by itself. 0 means the configured default
            (setting deck.hands_off_max_minutes, 30 unless set otherwise), which is also the largest value allowed.

        Returns:
          Token: Give it to End to release hands-off.
        """
        try:
            return self.guard.begin(who, reason, max_minutes)
        except BackendError as exc:
            raise HandsOffFailed(str(exc)) from None

    @sila.UnobservableCommand(errors=[HandsOffFailed])
    async def end(self, token: str) -> str:
        """
        Release hands-off, so the Fluent can move again. Moves nothing.

        Args:
          Token: The token Begin returned.

        Returns:
          Released: What was held, e.g. "hands-off by Franka (puts a plate on Nest7mm_Pos[1], since ...)".
        """
        try:
            return self.guard.end(token)
        except BackendError as exc:
            raise HandsOffFailed(str(exc)) from None

    @sila.UnobservableProperty()
    async def get_state(self) -> str:
        """Who holds hands-off, why, since and until when (also when another server on the Fluent PC holds it).
        Empty when free."""
        return self.guard.state()
