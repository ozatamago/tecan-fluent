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


def test_asc_list_format_runs_down_the_columns():
    # 2026-11-19 (Abs600.mth): blue ink in B2, D2, F2 / B4, D4, F4 (about 0.30) and B6, D6, F6 / B8, D8, F8 (about
    # 0.076); water only and empty wells about 0.04. Only the column order (A1, B1, ..., H1, A2) puts them there.
    r = parse_asc((FIX / "asc_list_format_20261119_blue.asc").read_text(encoding="latin-1"))
    g = r.values[0]
    high = [g[w] for w in ("B2", "D2", "F2", "B4", "D4", "F4")]
    mid = [g[w] for w in ("B6", "D6", "F6", "B8", "D8", "F8")]
    assert min(high) > 0.29 and 0.07 < min(mid) and max(mid) < 0.08
    others = [v for w, v in g.items() if w not in ("B2", "D2", "F2", "B4", "D4", "F4", "B6", "D6", "F6", "B8", "D8", "F8")]
    assert max(others) < 0.06
    assert r.metadata[1] == "Abs600.mth"
    # the 2026-08-13 file (yellow ink, too pale at 600 nm to show the order) still reads
    old = parse_asc((FIX / "asc_list_format.asc").read_text(encoding="latin-1")).values[0]
    assert len(old) == 96 and not any(math.isnan(v) for v in old.values())


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


def test_the_result_file_is_also_searched_in_the_method_export_folders():
    import base64

    calls = []
    text = (FIX / "asc_list_format_20261119_blue.asc").read_bytes()

    class _Backend:
        def _ssh_ps(self, cmd):
            calls.append(cmd)
            return "C:\\FluentData\\00_A600_Result\\ASC\\riken_x.asc\n" + base64.b64encode(text).decode()

    reader = FluentInfiniteReader(backend=_Backend(), config=InfiniteConfig())
    path, result = reader._fetch_asc("riken_x", 0)
    assert "'C:\\Users\\Public\\Documents\\Tecan\\Magellan Pro\\asc','C:\\FluentData'" in calls[0]
    assert path.endswith("riken_x.asc") and result.values[0]["B2"] > 0.29
