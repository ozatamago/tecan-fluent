"""FluentControl's own labware statements as SiLA commands (stage 4-3).

Each command sends one FluentControl statement, built (io/fluent/gripper/statements.py) from the same statement in
the 01-07 GUI scripts (tests/fixtures/gui_macros and gui_statements):

- AddLabware / RemoveLabware: AddLabwareDataV1 / RemoveLabwareDataV1 (bookkeeping only; nothing moves)
- TransferLabware: RGA1_TransferLabware to a location and site
- MoveLabwareToBase: RGA1_TransferLabware with MoveToBase (e.g. a lid back onto its plate)
- PutLidOn: RGA1_TransferLabware to the cover site of a plate (GetCoverSiteName / GetCoverSiteIndex with FixedSite,
  as in 03 line 76 and 07 line 124)
- GetFingers / DropFingers: CgaGetFingers / CgaDropFingers (the RGA picks up or puts back its gripper fingers)

They only work inside a run opened with RunControl.StartRun: FluentControl forgets labware added or moved when a
run ends, so a sequence (add a plate, move it, put a lid on it, ...) must stay in one run. Labware that the
PlateTransfer tracks across runs (MoveLabware / ReturnLabware) is refused here, so the two never disagree.
"""

from unitelabs.cdk import sila

from ....io.fluent.gripper.labware_tracker import LabwareTracker
from ....io.fluent.gripper.statements import (
    add_labware_xml,
    drop_fingers_xml,
    get_fingers_xml,
    lid_on_xml,
    remove_labware_xml,
    to_base_xml,
    transfer_xml,
)
from ....io.fluentcontrol.backend import BackendError, FluentOdtcBackend
from ....io.fluentcontrol.progress import with_progress


class LabwareCommandFailed(Exception):
    """The labware command was refused or failed. The description says why."""


class Labware(sila.Feature):
    """
    FluentControl's labware statements, one command each: register labware, move it with the RGA (plate gripper),
    put lids on and off, and pick up or put back the gripper fingers.

    Use them between RunControl.StartRun and EndRun: FluentControl forgets labware added or moved when a run
    ends. Labware handled by PlateTransfer.MoveLabware (tracked across runs) cannot be moved here.
    TransferLabware, MoveLabwareToBase, PutLidOn, GetFingers and DropFingers MOVE the arm.
    """

    def __init__(self, backend: FluentOdtcBackend, tracker: LabwareTracker | None = None):
        super().__init__(
            originator="jp.riken.bdr",
            category="tecan.fluent.gripper",
            identifier="Labware",
            name="RGA Gripper - Labware, Lids & Fingers",
            version="1.0",
        )
        self.backend = backend
        self.tracker = tracker

    def _check(self, *labware: str) -> None:
        if not self.backend.run_open:
            raise LabwareCommandFailed(
                "Start a run first (RunControl.StartRun): FluentControl forgets labware positions when a run ends"
            )
        if self.tracker is not None:
            for name in labware:
                if name in self.tracker.config.labware:
                    raise LabwareCommandFailed(
                        f"{name} is tracked by PlateTransfer; move it with MoveLabware / ReturnLabware"
                    )

    async def _send(self, label: str, xml: str, status: sila.Status) -> None:
        try:
            await with_progress(status, 1, lambda report: self.backend.run_steps([(label, xml)], report, label))
        except BackendError as exc:
            raise LabwareCommandFailed(str(exc)) from None

    @sila.ObservableCommand(errors=[LabwareCommandFailed])
    async def add_labware(
        self, label: str, labware_type: str, location: str, site: int, *, status: sila.Status
    ) -> None:
        """
        Tell FluentControl that a labware is at a position (AddLabware). Nothing moves.

        Args:
          Label: Name for the labware in this run, e.g. "TemplatePlate[001]".
          LabwareType: FluentControl labware type, e.g. "96 Well Skirted PCR_Custom".
          Location: Location name, e.g. "Nest7mm_Pos".
          Site: Site number (from 1).
        """
        self._check(label)
        await self._send(
            f"AddLabware {label} ({labware_type}) at {location}[{site}]",
            add_labware_xml(labware_type, label, location, site),
            status,
        )
        self.backend.session_labware[label] = labware_type

    @sila.ObservableCommand(errors=[LabwareCommandFailed])
    async def remove_labware(self, label: str, *, status: sila.Status) -> None:
        """
        Tell FluentControl that a labware is gone (RemoveLabware). Nothing moves.

        Args:
          Label: Name of the labware, e.g. "TemplatePlate[001]".
        """
        self._check(label)
        await self._send(f"RemoveLabware {label}", remove_labware_xml(label), status)
        self.backend.session_labware.pop(label, None)

    @sila.ObservableCommand(errors=[LabwareCommandFailed])
    async def transfer_labware(self, labware: str, location: str, site: int, *, status: sila.Status) -> None:
        """
        Move a labware (plate or lid) to a position with the RGA. MOVES the arm.

        Args:
          Labware: Name of the labware in this run, e.g. "Template_Lid_6mm[001]".
          Location: Target location name, e.g. "HotelMP_Pos".
          Site: Target site number (from 1).
        """
        self._check(labware)
        await self._send(f"RGA {labware} -> {location}[{site}]", transfer_xml(labware, location, site), status)

    @sila.ObservableCommand(errors=[LabwareCommandFailed])
    async def move_labware_to_base(self, labware: str, *, status: sila.Status) -> None:
        """
        Move a labware back to its base position with the RGA, e.g. a lid back onto its plate. MOVES the arm.

        Args:
          Labware: Name of the labware, e.g. "Template_Lid_6mm[001]".
        """
        self._check(labware)
        await self._send(f"RGA {labware} -> base", to_base_xml(labware), status)

    @sila.ObservableCommand(errors=[LabwareCommandFailed])
    async def put_lid_on(self, lid: str, plate: str, *, status: sila.Status) -> None:
        """
        Put a lid on a plate with the RGA (to the plate's cover site). MOVES the arm.

        Args:
          Lid: Name of the lid, e.g. "ODTC_Lid[001]".
          Plate: Name of the plate, e.g. "TemplatePlate[001]".
        """
        self._check(lid, plate)
        await self._send(f"RGA {lid} -> lid of {plate}", lid_on_xml(lid, plate), status)

    @sila.ObservableCommand(errors=[LabwareCommandFailed])
    async def get_fingers(self, fingers: str, *, status: sila.Status) -> None:
        """
        Let the RGA pick up a set of gripper fingers. MOVES the arm.

        Args:
          Fingers: "Eccentric[001]" (used by 03 and 05) or "Centric[001]" (04 and 06).
        """
        self._check()
        try:
            xml = get_fingers_xml(fingers)
        except BackendError as exc:
            raise LabwareCommandFailed(str(exc)) from None
        await self._send(f"GetFingers {fingers}", xml, status)

    @sila.ObservableCommand(errors=[LabwareCommandFailed])
    async def drop_fingers(self, nest: str, *, status: sila.Status) -> None:
        """
        Let the RGA put its gripper fingers down. MOVES the arm.

        Args:
          Nest: "FES Eccentric Nest[001]" or "FES Centric Nest[001]", or empty to put them back where they came from.
        """
        self._check()
        try:
            xml = drop_fingers_xml(nest)
        except BackendError as exc:
            raise LabwareCommandFailed(str(exc)) from None
        await self._send(f"DropFingers {nest or '(back to source)'}", xml, status)
