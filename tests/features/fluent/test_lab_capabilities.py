"""The LabCapabilities feature on the synthetic database of tests/fixtures/capabilities_db. Dry run: nothing is sent."""

import asyncio
import json
import pathlib

import pytest

from unitelabs.tecan_fluent.apps.fluent780_all import Fluent780AllConnectorConfig, build_features
from unitelabs.tecan_fluent.features.fluent.lab_capabilities import SCHEMA, DatabaseUnavailable
from unitelabs.tecan_fluent.io.fluent.capabilities import catalog

DB = pathlib.Path(__file__).parents[2] / "fixtures" / "capabilities_db"


def _feature(database_root=DB, worktable="Test WT"):
    config = Fluent780AllConnectorConfig()  # dry run
    config.capabilities.database_root = str(database_root)
    config.capabilities.worktable = worktable
    return {type(x).__name__: x for x in build_features(config)}["LabCapabilities"]


def test_places_labware_tips_and_liquid_classes():
    f = _feature()

    async def scenario():
        places = {(p.location, p.site): p for p in await f.get_places()}
        tips = places[("Nest_Pos", 1)]
        assert tips.carrier == "Test Nest[001]" and tips.labware == "FCA, 200ul SBS FCA_ 200ul SBS[001]"
        assert tips.gripper_modes == ["Narrow", "Wide"] and tips.pipetting == "yes"
        assert places[("Hotel_Pos", 1)].pipetting == "no" and places[("Nest_Pos", 2)].labware == ""

        labware = {x.name: x for x in await f.get_labware_types()}
        assert set(labware) == {"FCA, 200ul SBS", "Test PCR 96", "Test Plate 96"}
        plate = labware["Test Plate 96"]
        assert (plate.kind, plate.columns, plate.rows, plate.grip_narrow_mm, plate.grip_force) == (
            "Microplate", 12, 8, 85.5, 20.0)

        (tip,) = await f.get_tip_types()
        assert (tip.tip_group, tip.capacity_ul, tip.filtered) == ("FCA DiTi 200µl", 220.0, False)
        assert tip.racks == ["FCA_ 200ul SBS[001] at Nest_Pos[1]"]

        classes = {lc.name: lc for lc in await f.get_liquid_classes()}
        assert classes["Test Water Single"].tip_groups == ["FCA DiTi 200µl: 2-200 uL"]
        assert classes["Test Water Multi"].tip_groups == ["FCA DiTi 200µl: equations without accuracy points multi"]
        assert not classes["Test Wash"].air_fca

    asyncio.run(scenario())


def test_catalog_commands_and_json():
    f = _feature()

    async def scenario():
        assert len(await f.get_constraints()) == len(catalog.CONSTRAINTS)
        assert all(n.startswith("[") for n in await f.get_notes())
        assert (await f.get_arms())[0].startswith("Air FCA 1 (pipetting arm, 8 channel(s))")
        instruments = {i.name: i for i in await f.get_instruments()}
        assert not instruments["Inheco ODTC 96"].on_worktable  # not on the synthetic worktable

        commands = await f.get_commands()
        names = {(c.feature.split("/")[2], c.command) for c in commands}
        assert ("LabCapabilities", "GetPlaces") not in names  # properties are not commands
        assert any(feature == "RunControl" for feature, _ in names)
        assert all(c.description for c in commands)

        state = json.loads(await f.get_current_state_json())
        assert state["busy"] is False and "read_at" in state

        doc = json.loads(await f.get_capabilities_json())
        assert doc["schema"] == SCHEMA and doc["worktable"] == "Test WT"
        assert len(doc["places"]) == 4 and doc["rga_settings"]["RegripStation"] == "Regrip_Test"
        assert len(doc["commands"]) == len(commands)

    asyncio.run(scenario())


def test_unreadable_database_is_reported():
    async def scenario():
        with pytest.raises(DatabaseUnavailable, match="not a FluentControl database"):
            await _feature(database_root=DB / "nowhere").get_places()
        with pytest.raises(DatabaseUnavailable, match="not found"):
            await _feature(worktable="No Such WT").get_capabilities_json()
        assert await _feature(database_root=DB / "nowhere").get_constraints()  # the catalog needs no database

    asyncio.run(scenario())
