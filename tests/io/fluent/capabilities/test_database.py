"""Reading the FluentControl database: a small synthetic database in tests/fixtures/capabilities_db (no namespaces
except where FluentControl uses them for shape types)."""

import pathlib

import pytest

from unitelabs.tecan_fluent.io.fluent.capabilities import commands, database

DB = pathlib.Path(__file__).parents[3] / "fixtures" / "capabilities_db"


def _place(caps, location, site):
    return next(p for p in caps.places if p.location == location and p.site == site)


def test_places_of_the_worktable():
    caps = database.load(DB, "Test WT")
    assert [(p.location, p.site) for p in caps.places] == [
        ("Nest_Pos", 1), ("Nest_Pos", 2), ("Nest_Pos_PCR", 1), ("Hotel_Pos", 1)]  # grids are left out

    tips = _place(caps, "Nest_Pos", 1)
    assert tips.parent == "Test Nest[001]" and tips.parent_type == "Test Nest"
    assert (tips.labware, tips.labware_type) == ("FCA_ 200ul SBS[001]", "FCA, 200ul SBS")
    assert tips.accepts == ["FCA, 200ul SBS", "Test Plate 96"]
    assert tips.gripper_modes == ["Narrow", "Wide"]  # the carrier allows fewer modes than the site template
    assert tips.pipetting is True

    empty = _place(caps, "Nest_Pos", 2)
    assert empty.labware is None and empty.gripper_modes == ["Narrow", "NarrowReverse", "Wide"]  # CGA 2 not used
    assert _place(caps, "Nest_Pos_PCR", 1).accepts == ["Test PCR 96"]

    hotel = _place(caps, "Hotel_Pos", 1)
    assert hotel.gripper_modes == ["Narrow"] and hotel.pipetting is False


def test_labware_tips_liquid_classes_and_rga():
    caps = database.load(DB, "Test WT")
    assert [c.name for c in caps.labware_types()] == ["FCA, 200ul SBS", "Test PCR 96", "Test Plate 96"]
    assert "Unused Plate" in [c.name for c in caps.labware_types(used_only=False)]
    plate = caps.components["c-plate"]
    assert plate.wells["columns"] == 12 and plate.wells["rows"] == 8
    assert plate.wells["well_volume_ul"] == pytest.approx(282.7, abs=0.1)  # cylinder d 6 mm, h 10 mm
    assert plate.attributes["Grip_Narrow"] == "85.5" and plate.height_mm == 14.4
    assert [t.name for t in caps.tip_types()] == ["FCA, 200ul SBS"]

    classes = {lc.name: lc for lc in caps.liquid_classes}
    water = classes["Test Water Single"]
    assert water.air_fca and water.tip_groups == {
        "FCA DiTi 200µl": {"min_ul": 2.0, "max_ul": 200.0, "multi_dispense": False}}  # the Fca part is ignored
    assert classes["Test Water Multi"].tip_groups["FCA DiTi 200µl"] == {
        "min_ul": None, "max_ul": None, "multi_dispense": True}
    assert not classes["Test Wash"].air_fca and classes["Test Wash"].tip_groups == {}
    assert caps.rga_settings == {"GripDetection": "1", "RegripStation": "Regrip_Test", "Force": "20", "Speed": "80"}


def test_missing_database_or_worktable():
    with pytest.raises(database.DatabaseError, match="not a FluentControl database"):
        database.load(DB / "nowhere", "Test WT")
    with pytest.raises(database.DatabaseError, match="not found"):
        database.load(DB, "No Such WT")
    other = database.load(DB, "Other WT")  # an empty frame: no places
    assert other.places == []


def test_command_docstrings():
    assert commands._pascal("move_labware") == "MoveLabware"
    head, args = commands._doc_parts("""
        Move a plate.

        Args:
          Source: Where from,
            as a location.
          Volume: In uL.

        Returns:
          Nothing.
        """)
    assert head == "Move a plate." and args == {"Source": "Where from, as a location.", "Volume": "In uL."}
    assert commands._type_name(list[str]) == "list[str]" and commands._type_name(int) == "int"
