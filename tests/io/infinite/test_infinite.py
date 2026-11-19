"""Tests for the Infinite 200 PRO (through Fluent) XML and ASC parsing. Connects to neither the device nor Fluent.

The XML in fixtures/ is exactly what was sent to the device (copied from probe_out of qpcr_water_demo.py).
The ASC files are results measured on the device in 2026-08.
"""

import math

import pytest

from fakes import FIXTURES as FIX
from unitelabs.tecan_fluent.io.fluent.gripper.statements import add_labware_xml, remove_labware_xml, rga_xml
from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError
from unitelabs.tecan_fluent.io.infinite.asc import parse_asc
from unitelabs.tecan_fluent.io.infinite.reader import TEMP_LABEL, FluentInfiniteReader, InfiniteConfig
from unitelabs.tecan_fluent.io.infinite.xml import magellan_xml


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_magellan_open_matches_device():
    assert magellan_xml("Magellan_Open") == read("magellan_open_20261009.xml")


def test_magellan_measure_matches_device():
    reader = FluentInfiniteReader(backend=None, config=InfiniteConfig())
    [(_, xml)] = reader.measure_steps("OFML_ColorMix3.mth", "qpcr_water_measure-pcr_261009_175940")
    assert xml == read("magellan_measure_20261009.xml")


def test_rga_matches_device():
    xml = rga_xml("96 Well Skirted PCR_Custom[001]", "ODTC_96_Pos", "1")
    assert xml == read("rga_plate_to_odtc_20261009.xml")


def test_measure_refuses_angle_brackets_and_unknown_macros():
    with pytest.raises(BackendError):
        magellan_xml("Magellan_Measure", r"C:\x\<YYMMDD-NNN>,Abs600.mth,0,0,0")
    with pytest.raises(BackendError):
        magellan_xml("Magellan_Shake")
    with pytest.raises(BackendError):
        magellan_xml("Magellan_Measure")


def test_load_measure_unload_is_one_run_in_the_proven_order():
    reader = FluentInfiniteReader(backend=None, config=InfiniteConfig())
    steps = reader.load_measure_unload_steps("96 Well Flat_Custom", "Nest7mm_Pos", 7, "OFML_Abs405.mth", "riken_x")
    assert [label for label, _ in steps] == [
        "AddLabware 96 Well Flat_Custom at Nest7mm_Pos[7]",
        "Magellan_Open",
        "RGA -> Regrip_Pos[1]",
        "RGA -> InfiniteM200_New[1]",
        "Magellan_Close",
        "Magellan_Measure OFML_Abs405.mth",
        "Magellan_Open",
        "RGA -> Regrip_Pos[1]",
        "RGA -> Nest7mm_Pos[7]",
        "Magellan_Close",
        f"RemoveLabware {TEMP_LABEL}",
    ]
    assert all(xml.startswith("<ScriptGroup>") for _, xml in steps)


def test_labware_statements():
    add = add_labware_xml("96 Well Flat_Custom", TEMP_LABEL, "Nest7mm_Pos", 7)
    assert "<LabwareLable>SiLA_ReaderPlate[001]</LabwareLable>" in add and "<Position>7</Position>" in add
    assert "<LabwareName>SiLA_ReaderPlate[001]</LabwareName>" in remove_labware_xml(TEMP_LABEL)


def test_asc_grid_format_three_labels():
    r = parse_asc((FIX / "asc_colormix3_20260818.asc").read_text(encoding="latin-1"))
    assert r.labels == ["Label1", "Label2", "Label3"]
    assert all(len(g) == 96 for g in r.values)
    assert r.metadata[1] == "OFML_ColorMix3.mth"


def test_asc_list_format_is_row_major():
    # 2026-08-13: yellow ink 10/20/50/100 uL in A4-D4. Row-major order matches the recorded OD
    # 0.0404/0.0422/0.0425/0.0425
    r = parse_asc((FIX / "asc_list_format.asc").read_text(encoding="latin-1"))
    g = r.values[0]
    assert [g["A4"], g["B4"], g["C4"], g["D4"]] == [0.0404, 0.0422, 0.0425, 0.0425]
    assert r.metadata[1] == "Abs600.mth"
    assert not any(math.isnan(v) for v in g.values())


def test_worktable_plate_follows_the_20260813_route():
    reader = FluentInfiniteReader(backend=None, config=InfiniteConfig())
    steps = reader.worktable_plate_steps("96 Well Flat_Custom[001]", "OFML_Abs405.mth", "riken_x")
    assert [label for label, _ in steps] == [
        "Magellan_Open",
        "RGA 96 Well Flat_Custom[001] -> Regrip_Pos[1]",
        "RGA 96 Well Flat_Custom[001] -> InfiniteM200_New[1]",
        "Magellan_Close",
        "Magellan_Measure OFML_Abs405.mth",
        "Magellan_Open",
        "RGA 96 Well Flat_Custom[001] -> Regrip_Pos[1]",
        "RGA 96 Well Flat_Custom[001] -> base",
        "Magellan_Close",
    ]


def test_a_worktable_plate_off_its_base_goes_back_where_it_was():
    reader = FluentInfiniteReader(backend=None, config=InfiniteConfig())
    steps = reader.worktable_plate_steps("96 Well Flat_Custom[001]", "OFML_Abs405.mth", "riken_x", ("Nest7mm_Pos", 1))
    label, xml = steps[-2]
    assert label == "RGA 96 Well Flat_Custom[001] -> Nest7mm_Pos[1]"
    assert xml == rga_xml("96 Well Flat_Custom[001]", "Nest7mm_Pos", "1", fixed_site=True)


class _Tracker:
    def __init__(self, deck):
        self.deck = deck
        self.positions = {"96 Well Flat_Custom[001]": ["Nest7mm_Pos", 1]}

    def where(self, labware):
        return tuple(self.positions[labware][:1]) + (int(self.positions[labware][1]),)


def _measure_with(tracker):
    import asyncio

    from unitelabs.tecan_fluent.features.infinite.plate_handling import PlateHandling

    reader = FluentInfiniteReader(backend=None, config=InfiniteConfig())
    seen = {}

    async def method_found(_method):
        return None

    async def run(steps, name, report):
        seen["steps"] = steps
        raise BackendError("stop here")

    reader.check_method, reader.run = method_found, run
    feature = PlateHandling(reader, tracker)

    class _Status:
        def update(self, *a, **k):
            pass

    try:
        asyncio.run(feature.measure_worktable_plate("96 Well Flat_Custom[001]", "OFML_Abs405.mth", status=_Status()))
    except Exception as exc:  # noqa: BLE001 - the error raised by run (or the refusal)
        seen["error"] = str(exc)
    return seen


def test_with_the_deck_state_a_plate_off_its_base_is_measured_from_where_it_is():
    seen = _measure_with(_Tracker(deck=object()))
    assert [label for label, _ in seen["steps"]][-2] == "RGA 96 Well Flat_Custom[001] -> Nest7mm_Pos[1]"
    assert seen["error"] == "stop here"


def test_without_the_deck_state_a_plate_off_its_base_is_refused():
    seen = _measure_with(_Tracker(deck=None))
    assert "steps" not in seen and "Use ReturnLabware first" in seen["error"]
