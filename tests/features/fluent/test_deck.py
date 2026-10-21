"""The Deck feature, and the RGA commands updating the deck state. Dry runs: nothing is sent, the deck state stays in
memory, the definitions come from a fake definition index."""

import asyncio

import pytest

from unitelabs.tecan_fluent.apps.fluent780_all import Fluent780AllConnectorConfig, build_features
from unitelabs.tecan_fluent.features.fluent.deck import DeckCommandFailed
from unitelabs.tecan_fluent.features.fluent.gripper.labware import LabwareCommandFailed
from unitelabs.tecan_fluent.io.fluent.deck.state import DeckConfig
from unitelabs.tecan_fluent.io.fluent.gripper.labware_tracker import PlateTransferConfig
from unitelabs.tecan_fluent.io.fluentcontrol.definitions import DefinitionView

PLATE = "96 Well Flat_Custom[001]"
LID = "Template_Lid_6mm[001]"


def view() -> DefinitionView:
    return DefinitionView(
        worktable="WT2411004293_Ver.0.5_OFML",
        labware_types={"96 Well Flat_Custom", "96 Well Skirted PCR_Custom", "FCA, 200ul SBS"},
        sites={"Nest7mm_Pos": 8, "Regrip_Pos": 1, "HotelMP_Pos": 4},
        labware={
            PLATE: {"type": "96 Well Flat_Custom", "location": "Nest7mm_Pos", "site": 6},
            LID: {"type": "Lid_6mm", "location": "HotelMP_Pos", "site": 1},
        },
    )


class _Status:
    def update(self, *a, **k):
        pass


def _features(tmp_path, with_deck=True):
    config = Fluent780AllConnectorConfig()  # dry run
    if with_deck:
        config.deck = DeckConfig(state_file=str(tmp_path / "deck.json"))
        config.plates = PlateTransferConfig(positions_file=str(tmp_path / "labware_positions.json"))
    f = {type(x).__name__: x for x in build_features(config)}
    if with_deck:
        f["Deck"].deck.definitions = view
    return f


def test_without_a_deck_state_the_commands_are_refused(tmp_path):
    f = _features(tmp_path, with_deck=False)

    async def scenario():
        assert await f["Deck"].get_layout() == ["no deck state configured (setting deck.state_file)"]
        assert await f["Deck"].get_tip_racks() == []
        with pytest.raises(DeckCommandFailed, match="No deck state is configured"):
            await f["Deck"].place_labware("Plate_A[001]", "96 Well Flat_Custom", "HotelMP_Pos", 2, "", "Franka")

    asyncio.run(scenario())
    assert f["RunControl"].backend.deck is None and f["PlateTransfer"].tracker.deck is None


def test_place_record_and_refusals(tmp_path):
    f = _features(tmp_path)
    deck, backend = f["Deck"], f["RunControl"].backend

    async def scenario():
        assert (
            await deck.place_labware("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 2, "", "Franka") == 1
        )
        with pytest.raises(DeckCommandFailed, match=r"HotelMP_Pos\[2\] is taken by Plate_A\[001\]"):
            await deck.place_labware("Plate_B[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 2, "", "Franka")
        with pytest.raises(DeckCommandFailed, match="Labware type 'Tube' is not defined"):
            await deck.place_labware("Plate_B[001]", "Tube", "HotelMP_Pos", 3, "", "Franka")
        assert await deck.place_tip_rack("FCA_ 200ul SBS[009]", "FCA, 200ul SBS", "HotelMP_Pos", 4, "full", "a person")
        assert await deck.set_contents("Plate_A[001]", ["A1"], "water", [150.0]) == 3
        assert await deck.move_labware_record("Plate_A[001]", "HotelMP_Pos", 3, "Kachaka") == 4
        layout = await deck.get_layout()
        assert layout[0] == "base worktable WT2411004293_Ver.0.5_OFML, version 4"
        assert layout[2].startswith("Plate_A[001]: 96 Well Skirted PCR_Custom at HotelMP_Pos[3] (placed by Franka")
        assert (await deck.get_tip_racks())[0].startswith("FCA_ 200ul SBS[009]: FCA, 200ul SBS at HotelMP_Pos[4] (full")
        # an open run already has its layout: changes to it are refused, contents are not
        await backend.start_run()
        with pytest.raises(DeckCommandFailed, match="A run is open"):
            await deck.remove_labware("Plate_A[001]", "Franka")
        assert await deck.set_contents("Plate_A[001]", ["A1"], "water", [100.0]) == 6  # 5: rack registered as full
        await backend.end_run()
        assert await deck.remove_labware("Plate_A[001]", "Franka") == 7

    asyncio.run(scenario())


def test_rga_moves_update_the_deck_state(tmp_path):
    f = _features(tmp_path)
    deck, lc, pt, backend = f["Deck"], f["Labware"], f["PlateTransfer"], f["RunControl"].backend
    state = deck.deck

    async def scenario():
        await deck.place_labware("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 2, "", "Franka")
        await backend.start_run()
        assert backend.session_labware == {"Plate_A[001]": "96 Well Skirted PCR_Custom"}  # registered at StartRun
        await lc.transfer_labware("Plate_A[001]", "Regrip_Pos", 1, status=_Status())
        assert state.entry("Plate_A[001]")["location"] == "Regrip_Pos"
        await lc.transfer_labware(LID, "HotelMP_Pos", 3, status=_Status())  # base-worktable lid: now listed
        assert state.entry(LID)["location"] == "HotelMP_Pos" and state.entry(LID)["moved_by"] == "RGA"
        await lc.put_lid_on(LID, "Plate_A[001]", status=_Status())  # assumed back at its base position
        assert state.entry(LID) is None
        with pytest.raises(LabwareCommandFailed, match="base position is not known"):
            await lc.move_labware_to_base("Plate_A[001]", status=_Status())
        await lc.add_labware("Temp[001]", "96 Well Flat_Custom", "Nest7mm_Pos", 1, status=_Status())
        await lc.transfer_labware("Temp[001]", "HotelMP_Pos", 4, status=_Status())  # only in this run: not recorded
        assert state.entry("Temp[001]") is None
        await backend.end_run()
        # PlateTransfer: the tracker is a view on the deck state, and the run start registers the position
        assert await pt.move_labware(PLATE, "Regrip_Pos", 1, status=_Status()) == "Regrip_Pos[1]"
        assert state.positions()[PLATE] == ["Regrip_Pos", 1]
        assert pt.tracker.move_steps(PLATE, "Nest7mm_Pos", 6)[0][0] == f"RGA {PLATE} -> Nest7mm_Pos[6]"
        steps, _ = state.registration()
        assert [label for label, _ in steps][:2] == [
            f"RemoveLabware {PLATE} (deck state, bookkeeping only)",
            f"AddLabware {PLATE} at Regrip_Pos[1] (deck state, bookkeeping only)",
        ]
        await pt.return_labware(PLATE, status=_Status())
        assert PLATE not in state.positions()

    asyncio.run(scenario())
