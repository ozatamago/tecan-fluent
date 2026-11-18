"""An RGA move is only reported as done when FluentControl's log shows that it ran.

The log lines are shaped like the output of fc_log.RGA_LOG_PS1 (time, severity, channel, message; tab separated) and
taken from FluentControl's log of 2026-11-18. Nothing is sent to a real FluentControl.
"""

import pytest

from unitelabs.tecan_fluent.io.fluent.gripper.statements import add_labware_xml, lid_on_xml, transfer_xml
from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError, FluentBackendConfig, FluentControlBackend
from unitelabs.tecan_fluent.io.fluentcontrol.fc_log import rga_labware, rga_move_outcome

API = "Tecan/Fluent Control/Developer/API/ofml"
RGA = "Tecan/Fluent Control/Developer/Driver/Application Driver/RGA 1"
DRIVER = "Tecan/Fluent Control/Developer/Driver/Application Driver"
RECEIVED_RGA = (
    'Received command <ScriptGroup> <Objects> <Object Type="Tecan.VisionX.ApplicationDriver.ApplicationDriverBase.'
    'ApplicationDriverMacro"> <ApplicationDriverMacro Version="1" Name="RGA1_TransferLabware" ModuleName="RGA 1"'
)
RECEIVED_ADD = (
    'Received command <ScriptGroup> <Objects> <Object Type="Tecan.Core.Scripting.Worktable.Data.AddLabwareDataV1">'
)


def line(stamp: str, channel: str, msg: str, severity: str = "Info") -> str:
    return f"2026-11-18 {stamp}\t{severity}\t{channel}\t{msg}"


# 11:53:32: the lid really went onto its plate (ExecuteCommand took 5.4 s)
MOVED = "\n".join(
    [
        line("11:53:32.318", API, RECEIVED_RGA),
        line(
            "11:53:32.535",
            RGA,
            "Move CulturePlate_Lid[001] from Nest7mm_Pos position 1 NARROW to 96Microplate_CoverSite_4 position 1 "
            "NARROW. LidStatus = NoHandle Source offset: 0.00,0.00,0.00",
        ),
        line("11:53:32.535", RGA, "Move PostPath: X: 834.25, Y: 277, Z: 140, C: 180, G: 89.5"),
        line("11:53:33.270", RGA, "Grip: Close gripper to 75.5 with 10% force"),
        line("11:53:34.238", RGA, "Gripper action was successful."),
    ]
)

# 11:28:35: the lid was to go onto the cover site it already occupied; ExecuteCommand returned after 0.015 s and
# FluentControl logged nothing more for 7 minutes (only Execute Checks / RecoveryHandler, not in RGA_LOG_PS1's output)
NOT_MOVED = "\n".join(
    [
        line("11:28:33.782", API, RECEIVED_ADD),
        line("11:28:35.737", API, RECEIVED_RGA),
    ]
)

# 11:21:56: a move that started and failed
FAILED = "\n".join(
    [
        line("11:21:56.100", API, RECEIVED_RGA),
        line(
            "11:21:56.300", RGA, "Move Plate[001] from Nest7mm_Pos position 0 NARROW to Regrip_Pos position 0 NARROW."
        ),
        line("11:21:56.712", "Tecan/Fluent Control/Instrument/Compound", "Move failed"),
        line(
            "11:21:56.724",
            DRIVER,
            "Execution of move failed: At least one axis is not in ready state. ArmID: CGA:1",
            "Error",
        ),
    ]
)


def test_a_move_that_ran_is_found():
    out = rga_move_outcome(MOVED, "CulturePlate_Lid[001]")
    assert out["status"] == "moved"
    assert out["received"] == "2026-11-18 11:53:32.318"
    assert out["move"]["labware"] == "CulturePlate_Lid[001]"
    assert out["move"]["to"] == "96Microplate_CoverSite_4 position 1 NARROW"


def test_a_received_command_without_a_move_is_not_moved():
    out = rga_move_outcome(NOT_MOVED, "CulturePlate_Lid[001]")
    assert out == {"status": "not_moved", "received": "2026-11-18 11:28:35.737"}


def test_a_failed_move_is_failed():
    out = rga_move_outcome(FAILED, "Plate[001]")
    assert out["status"] == "failed"
    assert "At least one axis is not in ready state" in out["errors"][0]
    # "Move failed" of the instrument (severity Info) is not counted twice
    assert len(out["errors"]) == 1


def test_moving_other_labware_is_failed():
    out = rga_move_outcome(MOVED, "Other_Lid[001]")
    assert out["status"] == "failed" and "not Other_Lid[001]" in out["errors"][0]


def test_no_rga_command_in_the_log_is_not_logged():
    assert rga_move_outcome(line("11:28:33.782", API, RECEIVED_ADD), "X")["status"] == "not_logged"
    assert rga_move_outcome("", "X")["status"] == "not_logged"


def test_only_the_first_rga_command_is_looked_at():
    # the move of the next command does not count for this one
    text = "\n".join([NOT_MOVED, *MOVED.splitlines()])
    assert rga_move_outcome(text, "CulturePlate_Lid[001]")["status"] == "not_moved"


def test_labware_of_an_rga_statement():
    assert rga_labware(lid_on_xml("CulturePlate_Lid[001]", "CulturePlate[001]")) == "CulturePlate_Lid[001]"
    assert rga_labware(transfer_xml("Plate[001]", "Regrip_Pos", 1)) == "Plate[001]"
    assert rga_labware("<nothing/>") == ""


# ---- the backend: ExecuteCommand returning is not enough for an RGA move
class _Channel:
    def __init__(self):
        self.sent = []

    def ExecuteCommand(self, xml):  # noqa: N802 - name of the UniteLabs connector's command
        self.sent.append(xml)


class _Client:
    def __init__(self):
        self.ExecutionChannelController = _Channel()


def _backend(log_text, now="2026-11-18 11:28:35.700"):
    backend = FluentControlBackend(FluentBackendConfig(dry_run=False, rga_log_wait_s=0.0))
    backend._client = _Client()
    reads = []

    def read(since):
        reads.append(since)
        if isinstance(log_text, Exception):
            raise log_text
        return log_text

    backend._pc_now = lambda: now
    backend._read_rga_log = read
    return backend, reads


LID = (
    "RGA CulturePlate_Lid[001] -> lid of CulturePlate[001]",
    lid_on_xml("CulturePlate_Lid[001]", "CulturePlate[001]"),
)


def test_an_rga_move_that_did_not_run_fails_and_stops_the_remaining_commands():
    backend, reads = _backend(NOT_MOVED)
    checks = []
    after = ("AddLabware X", add_labware_xml("96 Well Flat_Custom", "X[001]", "Nest7mm_Pos", 1))
    with pytest.raises(BackendError) as caught:
        backend._execute([LID, after], lambda _: None, checks)
    assert "did not move anything" in str(caught.value)
    assert "Nothing was recorded as moved" in str(caught.value)
    assert reads == ["2026-11-18 11:28:35.700"]  # read from just before the command was sent
    assert len(backend._client.ExecutionChannelController.sent) == 1  # the next command was not sent
    [check] = checks
    assert check["status"] == "not_moved" and check["suspiciously_fast"] is True


def test_an_rga_move_that_ran_is_recorded():
    backend, _ = _backend(MOVED)
    checks = []
    backend._execute([LID], lambda _: None, checks)
    [check] = checks
    assert check["status"] == "moved" and check["checked"] is True
    assert check["labware"] == "CulturePlate_Lid[001]"


def test_a_failed_rga_move_fails():
    backend, _ = _backend(FAILED)
    with pytest.raises(BackendError, match="did not complete"):
        backend._execute([("RGA Plate", transfer_xml("Plate[001]", "Regrip_Pos", 1))], lambda _: None, [])


def test_an_unreadable_log_does_not_block_but_is_recorded():
    backend, _ = _backend(RuntimeError("no SSH"))
    checks = []
    backend._execute([LID], lambda _: None, checks)
    [check] = checks
    assert check["checked"] is False and "no SSH" in check["reason"]

    backend, reads = _backend(MOVED, now="")  # the PC time could not be read: the log is not read at all
    checks = []
    backend._execute([LID], lambda _: None, checks)
    assert reads == [] and checks[0]["checked"] is False


def test_a_command_missing_from_the_log_does_not_block_but_is_recorded():
    backend, _ = _backend(line("11:28:33.782", API, RECEIVED_ADD))
    checks = []
    backend._execute([LID], lambda _: None, checks)
    assert checks[0]["status"] == "not_logged" and checks[0]["checked"] is False


def test_other_commands_and_the_deck_registration_are_not_checked():
    backend, reads = _backend(NOT_MOVED)
    checks = []
    backend._execute([("AddLabware X", add_labware_xml("T", "X[001]", "Nest7mm_Pos", 1))], lambda _: None, checks)
    backend._execute([LID], lambda _: None)  # no checks list: as for the deck registration
    assert reads == [] and checks == []
    backend.config.verify_rga_moves = False
    backend._execute([LID], lambda _: None, checks)
    assert reads == [] and checks == []
