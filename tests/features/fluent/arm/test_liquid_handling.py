"""Stage 4-4 pipetting commands: XML equal to what ran in August 2026, and the checks before sending."""

import asyncio

import pytest

from fakes import _S, _setup
from fakes import FIXTURES as FIX
from unitelabs.tecan_fluent.features.fluent.arm.liquid_handling import LiquidHandlingFailed
from unitelabs.tecan_fluent.io.fluent.arm.statements import (
    drop_tips_xml,
    get_tips_xml,
    move_arm_xml,
    pipetting_xml,
    set_next_tip_position_xml,
    well_index,
    wells_fields,
)
from unitelabs.tecan_fluent.io.fluentcontrol.statements import wrap


def obj(xml: str) -> list[str]:
    lines = [ln.strip() for ln in xml.splitlines() if ln.strip()]
    start = next(i for i, ln in enumerate(lines) if ln.startswith("<Object "))
    end = max(i for i, ln in enumerate(lines) if ln == "</Object>")
    # "&gt;" and ">" are the same text in XML (the GUI writes "&gt;", the August XML had ">")
    return [ln.replace("&gt;", ">") for ln in lines[start : end + 1] if not ln.startswith("<LineNumber>")]


def ref(path: str) -> list[str]:
    return obj((FIX / path).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("xml", "fixture"),
    [
        (get_tips_xml("FCA, 200ul SBS", [1]), "liha_verified/gettips_1ch.xml"),
        (get_tips_xml("FCA, 1000ul SBS", list(range(1, 9))), "liha_verified/gettips_8ch_1000.xml"),
        (
            pipetting_xml("Aspirate", "1.5ml Sarstedt[001]", ["A1"], [20], "Water Free Multi", [1], 4, 6),
            "liha_verified/aspirate_1ch.xml",
        ),
        (
            pipetting_xml("Dispense", "OFML_TestPlate", ["A1"], [20], "Water Free Multi", [1], 8, 12),
            "liha_verified/dispense_1ch.xml",
        ),
        (
            pipetting_xml("Mix", "OFML_TestPlate", ["A1"], [15], "Water Mix_1", [1], 8, 12, cycles=5),
            "liha_verified/mix_1ch.xml",
        ),
        (
            pipetting_xml(
                "Aspirate", "4 Well SBS Trough[001]", ["A1"] * 8, [960] * 8, "Water Free Multi", list(range(1, 9)), 1, 4
            ),
            "liha_verified/asp_trough_8ch.xml",
        ),
        (
            pipetting_xml(
                "Dispense",
                "96 Well Flat_Custom[001]",
                [f"{r}1" for r in "ABCDEFGH"],
                [150] * 8,
                "Water Free Multi",
                list(range(1, 9)),
                8,
                12,
            ),
            "liha_verified/dis_flat_col1.xml",
        ),
        (drop_tips_xml(list(range(1, 9))), "gui_statements/LihaDropTipsScriptCommandDataV2_3.xml"),
        (
            move_arm_xml("100ml_Custom_1", "A1", list(range(1, 9)), 1, 1),
            "fluentcontrol_scripts/movearm_airfca_leakage_test.xml",
        ),
    ],
)
def test_matches_xml_that_ran_on_the_instrument(xml, fixture):
    assert obj(xml) == ref(fixture)


def test_get_tips_can_name_the_rack():
    assert "<LabwareName>FCA_ 1000ul SBS[002]</LabwareName>" in get_tips_xml(
        "FCA, 1000ul SBS", [1], "FCA_ 1000ul SBS[002]"
    )


def test_set_next_tip_position_is_the_form_accepted_on_the_instrument():
    # sent inside an open run on 2026-11-18; the next GetTips took the tip at C1
    assert set_next_tip_position_xml("FCA_ 1000ul SBS[002]", "c1") == wrap(
        '<Object Type="Tecan.Core.Scripting.Worktable.SetNextTipPositionStatement">\n'
        "<SetNextTipPositionStatement>\n"
        "<LabwareName>FCA_ 1000ul SBS[002]</LabwareName>\n"
        "<SelectedWellIndexes>\n"
        '<Object Type="System.Int32">\n'
        "<int>2</int>\n"
        "</Object>\n"
        "</SelectedWellIndexes>\n"
        "<SelectedWellsString>C1</SelectedWellsString>\n"
        "<IsBreakpoint>False</IsBreakpoint>\n"
        "<IsDisabledForExecution>False</IsDisabledForExecution>\n"
        "<LineNumber>1</LineNumber>\n"
        "</SetNextTipPositionStatement>\n"
        "</Object>"
    )
    assert "<int>8</int>" in set_next_tip_position_xml("R", "A2") and "<int>95</int>" in set_next_tip_position_xml(
        "R", "H12"
    )
    with pytest.raises(Exception, match="outside the labware"):
        set_next_tip_position_xml("R", "A13")


def test_move_arm_one_channel_at_travel_height():
    xml = move_arm_xml("4 Well SBS Trough[001]", "A1", [1], 1, 4)
    assert "<SelectedWellsString>1 * A1</SelectedWellsString>" in xml
    assert "<LabwareName>4 Well SBS Trough[001]</LabwareName>" in xml
    assert "<MovementType>travelToLabware</MovementType>" in xml and "<ZCustomVector>ZTravel</ZCustomVector>" in xml
    assert xml.count("<int>") == 1


def test_well_numbering_is_column_major():
    assert well_index("A1", 8, 12) == 0 and well_index("H1", 8, 12) == 7 and well_index("A2", 8, 12) == 8
    assert well_index("A3", 1, 4) == 2
    assert wells_fields(["A1"] * 8, 1, 4) == ("0;0;0;0;0;0;0;0;", "8 * A1")
    assert wells_fields([f"{r}1" for r in "ABCDEFGH"], 8, 12) == ("0>1>7;", "A1 - H1")
    with pytest.raises(Exception, match="outside the labware"):
        well_index("I1", 8, 12)


# ---- the checks, with a stand-in for the FluentControl definitions (tests/fakes.py)
def test_a_water_transfer_and_the_refusals():
    lh, lc, backend = _setup()
    S = _S()

    async def scenario():
        with pytest.raises(LiquidHandlingFailed, match="Start a run first"):
            await lh.get_tips("FCA, 200ul SBS", [1], "", status=S)
        await backend.start_run()
        await lc.add_labware("Water[001]", "4 Well SBS Trough", "Nest7mm_Pos", 5, status=S)
        await lc.add_labware("Plate[001]", "96 Well Flat_Custom", "Nest7mm_Pos", 2, status=S)
        with pytest.raises(LiquidHandlingFailed, match="have no tips"):
            await lh.aspirate("Water[001]", ["A1"], [50], "Water Free Single", [1], status=S)
        await lh.get_tips("FCA, 200ul SBS", [1], "", status=S)
        with pytest.raises(LiquidHandlingFailed, match="already have tips"):
            await lh.get_tips("FCA, 200ul SBS", [1], "", status=S)
        with pytest.raises(LiquidHandlingFailed, match="more than a FCA, 200ul SBS tip holds"):
            await lh.aspirate("Water[001]", ["A1"], [180], "Water Free Single", [1], status=S)
        with pytest.raises(LiquidHandlingFailed, match="neither added in this run"):
            await lh.aspirate("Elsewhere[001]", ["A1"], [50], "Water Free Single", [1], status=S)
        await lh.aspirate("Water[001]", ["A1"], [50], "Water Free Single", [1], status=S)
        with pytest.raises(LiquidHandlingFailed, match="already aspirated with these tips"):
            await lh.aspirate("Water[001]", ["A1"], [20], "Water Free Single", [1], status=S)
        with pytest.raises(LiquidHandlingFailed, match="holds 50 ul; cannot dispense 60"):
            await lh.dispense("Plate[001]", ["A1"], [60], "Water Free Single", [1], status=S)
        await lh.dispense("Plate[001]", ["A1"], [50], "Water Free Single", [1], status=S)
        with pytest.raises(Exception, match="Tips are still mounted"):
            await backend.end_run()
        await lh.drop_tips([1], status=S)
        assert await backend.end_run() == 6

    asyncio.run(scenario())


def test_liquid_class_without_settings_for_the_tip_and_10ul_on_pcr_are_refused():
    lh, lc, backend = _setup()
    S = _S()

    async def scenario():
        await backend.start_run()
        await lc.add_labware("Water[001]", "4 Well SBS Trough", "Nest7mm_Pos", 5, status=S)
        await lc.add_labware("Pcr[001]", "96 Well Skirted PCR_Custom", "Nest7mm_Pos", 2, status=S)
        await lh.get_tips("FCA, 10ul SBS", [1], "", status=S)
        with pytest.raises(LiquidHandlingFailed, match="no Air FCA settings for FCA DiTi 10µl"):
            await lh.aspirate("Water[001]", ["A1"], [5], "Water Free Single", [1], status=S)
        with pytest.raises(LiquidHandlingFailed, match="10 ul tips do not reach"):
            await lh.aspirate("Pcr[001]", ["A1"], [5], "Water Free Single", [1], status=S)
        await lh.drop_tips([1], status=S)
        await backend.end_run()

    asyncio.run(scenario())


def test_50ul_tips_and_their_liquid_class_settings():
    lh, lc, backend = _setup()
    S = _S()

    async def scenario():
        await backend.start_run()
        await lc.add_labware("Water[001]", "4 Well SBS Trough", "Nest7mm_Pos", 5, status=S)
        await lh.get_tips("FCA, 50ul SBS", [1], "FCA_ 50ul SBS[001]", status=S)
        await lh.get_tips("FCA, 50ul Filtered SBS", [2], "", status=S)
        assert backend.tips[1]["group"] == "FCA DiTi 50µl" and backend.tips[1]["capacity"] == 45
        with pytest.raises(LiquidHandlingFailed, match="more than a FCA, 50ul SBS tip holds"):
            await lh.aspirate("Water[001]", ["A1"], [46], "Water Free Single", [1], status=S)
        await lh.aspirate("Water[001]", ["A1"], [30], "Water Free Single", [1], status=S)
        with pytest.raises(LiquidHandlingFailed, match="no Air FCA settings for FCA DiTi 50µl Filtered"):
            await lh.aspirate("Water[001]", ["A1"], [30], "Water Free Single", [2], status=S)
        await lh.drop_tips([1, 2], status=S)
        await backend.end_run()

    asyncio.run(scenario())


def test_set_next_tip_position_needs_a_run_and_sends_the_statement():
    lh, _lc, backend = _setup()
    S = _S()
    sent = []
    run_steps = backend.run_steps

    async def capture(steps, *args, **kwargs):
        sent.extend(steps)
        return await run_steps(steps, *args, **kwargs)

    backend.run_steps = capture

    async def scenario():
        with pytest.raises(LiquidHandlingFailed, match="Start a run first"):
            await lh.set_next_tip_position("FCA_ 1000ul SBS[002]", "C1", status=S)
        await backend.start_run()
        with pytest.raises(LiquidHandlingFailed, match="outside the labware"):
            await lh.set_next_tip_position("FCA_ 1000ul SBS[002]", "I1", status=S)
        await lh.set_next_tip_position("FCA_ 1000ul SBS[002]", "c1", status=S)
        await backend.end_run()

    asyncio.run(scenario())
    assert sent == [
        ("SetNextTipPosition FCA_ 1000ul SBS[002] C1", set_next_tip_position_xml("FCA_ 1000ul SBS[002]", "C1"))
    ]


# ---- the next tip of the racks the deck state follows, from FluentControl's log
GET_TIPS_LOG = (
    "2026-11-18 10:00:01.000\tExecution parameters for 'Get Tips' at line 1: Worktable: WT ModifiedLabware: "
    "FCA_ 200ul SBS[009] ModifiedDitiType: TOOLTYPE:LiHa.TecanDiTi/TOOLNAME:FCA, 200ul SBS ModifiedSelectedTipIndexes: "
    "0, 1 ModifiedSelectedWellIndexes: 2, 3 ModifiedAirgapSpeed: 70.00 ul/s\n"
)


class LogPc:
    def __init__(self, logs):
        self.logs = list(logs)
        self.reads = 0

    def run_ps(self, script, timeout):
        if "Get-Date" in script:
            return b"2026-11-18 10:00:00.000"
        self.reads += 1
        return (self.logs.pop(0) if self.logs else "").encode()


def _deck_with_partial_rack(tmp_path):
    from unitelabs.tecan_fluent.io.fluent.deck.state import DeckConfig, DeckState

    d = DeckState(DeckConfig(state_file=str(tmp_path / "deck.json")), "WT", definitions=None)
    d.place_tip_rack("FCA_ 200ul SBS[009]", "FCA, 200ul SBS", "HotelMP_Pos", 4, "C1", "a person")
    return d


def test_tip_follower_moves_the_next_tip_on_from_the_log(tmp_path, monkeypatch):
    from unitelabs.tecan_fluent.features.fluent.arm import liquid_handling

    monkeypatch.setattr(liquid_handling.time, "sleep", lambda s: None)
    d = _deck_with_partial_rack(tmp_path)
    pc = LogPc(["", GET_TIPS_LOG])  # the log write lags once
    f = liquid_handling._TipFollower(d, pc, ["FCA_ 200ul SBS[009]"], "2026-11-18 10:00:00.000", "GetTips")
    out = f.after(f.read())
    assert pc.reads == 2 and out["tip_tracking"]["taken"] == {"FCA_ 200ul SBS[009]": [2, 3]}
    assert d.entry("FCA_ 200ul SBS[009]")["tips"]["next_well"] == "E1"


def test_tip_follower_marks_the_racks_used_when_the_log_shows_no_tips(tmp_path, monkeypatch):
    from unitelabs.tecan_fluent.features.fluent.arm import liquid_handling

    monkeypatch.setattr(liquid_handling.time, "sleep", lambda s: None)
    d = _deck_with_partial_rack(tmp_path)
    f = liquid_handling._TipFollower(d, LogPc([]), ["FCA_ 200ul SBS[009]"], "2026-11-18 10:00:00.000", "GetTips")
    assert "shows no Get Tips" in f.after(f.read())["tip_tracking"]["unknown"]
    assert d.entry("FCA_ 200ul SBS[009]")["tips"]["kind"] == "used"
    # after a failed command, nothing is assumed when the log shows nothing
    d.set_tip_rack_next_well("FCA_ 200ul SBS[009]", "C1")
    f = liquid_handling._TipFollower(d, LogPc([]), ["FCA_ 200ul SBS[009]"], "2026-11-18 10:00:00.000", "GetTips")
    f.after_failure()
    assert d.entry("FCA_ 200ul SBS[009]")["tips"] == {
        "kind": "partial",
        "next_well": "C1",
        "since": d.entry("FCA_ 200ul SBS[009]")["tips"]["since"],
        "set_by": "",
    }


def test_get_tips_follows_only_tracked_racks(tmp_path):
    lh, _lc, backend = _setup()
    d = _deck_with_partial_rack(tmp_path)
    backend.deck = d
    lh.pc = LogPc([])
    assert lh._tip_follower("FCA, 200ul SBS", "", "x") is None  # a dry run: nothing is followed
    backend.config.dry_run = False
    try:
        assert lh._tip_follower("FCA, 200ul SBS", "", "x").candidates == ["FCA_ 200ul SBS[009]"]
        assert lh._tip_follower("FCA, 200ul SBS", "FCA_ 200ul SBS[009]", "x").candidates == ["FCA_ 200ul SBS[009]"]
        assert lh._tip_follower("FCA, 200ul SBS", "FCA_ 200ul SBS[001]", "x") is None  # FluentControl's own count
        assert lh._tip_follower("FCA, 10ul SBS", "", "x") is None
    finally:
        backend.config.dry_run = True


def test_tips_taken_are_read_from_get_tips_entries_of_the_log():
    from unitelabs.tecan_fluent.io.fluentcontrol.fc_log import tips_taken

    assert tips_taken((FIX / "fc_log_worklist.txt").read_text(encoding="utf-8")) == {"FCA_ 200ul SBS[001]": [77, 78]}
    assert tips_taken(GET_TIPS_LOG) == {"FCA_ 200ul SBS[009]": [2, 3]}
    assert tips_taken("") == {}


def test_get_tips_from_a_partial_rack_sets_its_next_well_right_before(tmp_path):
    # Set Available Tips marks only the given well as available (2026-11-18: the GetTips after the next one raised
    # FCA_RTE_004_001), so it is sent again before every GetTips from the rack, in the same operation
    lh, _lc, backend = _setup()
    S = _S()
    d = _deck_with_partial_rack(tmp_path)
    backend.deck = d
    rack = "FCA_ 200ul SBS[009]"
    sent = []
    run_steps = backend.run_steps

    async def capture(steps, *args, **kwargs):
        sent.append(list(steps))
        return await run_steps(steps, *args, **kwargs)

    backend.run_steps = capture

    async def scenario():
        await backend.start_run()
        with pytest.raises(LiquidHandlingFailed, match="neighbouring"):
            await lh.get_tips("FCA, 200ul SBS", [1, 3], rack, status=S)
        with pytest.raises(LiquidHandlingFailed, match=r"Only 6 tip\(s\) left in column 1 from C1"):
            await lh.get_tips("FCA, 200ul SBS", [1, 2, 3, 4, 5, 6, 7], rack, status=S)
        await lh.get_tips("FCA, 200ul SBS", [1], rack, status=S)
        await lh.drop_tips([1], status=S)
        d.tips_taken({rack: [2]}, [rack], "GetTips")  # what the log says on the instrument (not read in a dry run)
        await lh.get_tips("FCA, 200ul SBS", [1, 2, 3], rack, status=S)  # D1, E1, F1 with three channels
        await lh.drop_tips([1, 2, 3], status=S)
        await lh.get_tips("FCA, 200ul SBS", [1], "FCA_ 200ul SBS[001]", status=S)  # not followed: GetTips only
        await lh.drop_tips([1], status=S)
        await backend.end_run()

    asyncio.run(scenario())
    gets = [steps for steps in sent if any(label.startswith("GetTips") for label, _ in steps)]
    assert gets == [
        [
            (f"SetNextTipPosition {rack} C1 (deck state)", set_next_tip_position_xml(rack, "C1")),
            (f"GetTips FCA, 200ul SBS ch[1] from {rack}", get_tips_xml("FCA, 200ul SBS", [1], rack)),
        ],
        [
            (
                f"SetNextTipPosition {rack} D1, E1, F1 (deck state)",
                set_next_tip_position_xml(rack, ["D1", "E1", "F1"]),
            ),
            (f"GetTips FCA, 200ul SBS ch[1, 2, 3] from {rack}", get_tips_xml("FCA, 200ul SBS", [1, 2, 3], rack)),
        ],
        [
            (
                "GetTips FCA, 200ul SBS ch[1] from FCA_ 200ul SBS[001]",
                get_tips_xml("FCA, 200ul SBS", [1], "FCA_ 200ul SBS[001]"),
            )
        ],
    ]


def test_several_tips_are_marked_in_one_set_available_tips():
    from unitelabs.tecan_fluent.io.fluent.arm.statements import tip_wells_from

    one = set_next_tip_position_xml("R[001]", "C1")
    assert "<int>2</int>" in one and "<SelectedWellsString>C1</SelectedWellsString>" in one
    three = set_next_tip_position_xml("R[001]", ["G4", "H4", "A5"])
    assert (
        three.count("<int>") == 3 and "<int>30</int>" in three and "<int>31</int>" in three and "<int>32</int>" in three
    )
    assert "<SelectedWellsString>G4 - A5</SelectedWellsString>" in three  # consecutive indexes: the GUI's range form
    assert "<SelectedWellsString>A9, C9</SelectedWellsString>" in set_next_tip_position_xml("R[001]", ["A9", "C9"])
    assert tip_wells_from("F4", 3) == ["F4", "G4", "H4"]
    with pytest.raises(Exception, match="Only 2 tip"):
        tip_wells_from("G4", 3)
