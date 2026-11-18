"""The RGA clearance check (io/fluent/rga_clearance.py): the geometry, the 11 real events it was validated against, and
the check of transfers against a deck. Nothing is sent to FluentControl."""

import pytest

from unitelabs.tecan_fluent.io.fluent import rga_clearance as rc

GEO = rc.Geometry.load()

# ---- the 11 events of 2026-11-17/18 the model was validated against (5 collisions, 6 clear moves)
# Sites of the right part of the deck (TCP positions); L = left column of 7 mm nests (X 834.25), R = right (X 984.25)
XY = {
    "Regrip": (834.25, 469.3),
    "N1": (834.25, 373.0),
    "N2": (834.25, 277.0),
    "N3": (834.25, 181.0),
    "N4": (984.25, 469.3),
    "N5": (984.25, 373.0),
    "N6": (984.25, 277.0),
    "N7": (984.25, 181.0),
    "CPLC3": (684.4, 200.4),
    "BS": (683.8, 85.8),
}
TOP = {"plate_lid": 21.0, "plate": 18.5, "trough_lid": 50.0, "trough": 48.0, "rack1000_lid": 116.0, "rack1000": 110.0,
       "tiplid": 22.0}  # fmt: skip
CARRY = {"plate_lid": (2.0, 12.0), "plate": (3.0, 11.4), "lid": (3.0, 6.0), "rlid": (3.0, 12.0)}
EVENTS = [
    # name, site, TCP Z of the grip, C, G, carried, what stood where, collided on the instrument
    ("16:51 B lid off N2, lidded 1000 ul rack on N5", "N2", 14.7, 180, 89.5, "lid",
     {"N5": "rack1000_lid", "N3": "trough_lid", "N2": "plate"}, True),
    ("16:32 WIDE grip at Regrip Z64, lidded 1000 ul rack on N1 (FluentControl refused)", "Regrip", 64, 90, 131.8,
     "plate", {"N1": "rack1000_lid", "N5": "trough_lid"}, True),
    ("13:08 plate at Regrip, lidded trough on N5, plates on N6 N7", "Regrip", 7.1, 180, 82.4, "plate_lid",
     {"N5": "trough_lid", "N6": "plate_lid", "N7": "plate_lid"}, False),
    ("13:09 plate at N7, lidded trough on N5", "N7", 7.1, 180, 82.4, "plate_lid",
     {"N5": "trough_lid", "N6": "plate_lid"}, False),
    ("15:46 1000 ul rack lid off N1 at Z104, trough without lid on N5", "N1", 104.1, 180, 83.6, "rlid",
     {"N5": "trough", "N6": "plate_lid", "N1": "rack1000"}, False),
    ("15:46 1000 ul rack lid onto N3 at Z10, N7 empty", "N3", 10.1, 180, 83.6, "rlid",
     {"N5": "trough", "N6": "plate_lid", "N1": "rack1000"}, False),
    ("12:0x plate at Regrip, trough lid parked on N4", "Regrip", 7.1, 180, 82.4, "plate_lid", {"N4": "tiplid"}, True),
    ("12:11 plate onto N1, lidded plate on N5", "N1", 7.1, 180, 82.4, "plate_lid", {"N5": "plate_lid"}, True),
    ("11/17 plate at CPLC 3, lidded 1000 ul rack on N3", "CPLC3", 74.0, 180, 82.4, "plate_lid",
     {"N3": "rack1000_lid"}, True),
    ("13:56 plate at CPLC 3, nothing on N2 N3", "CPLC3", 74.0, 180, 82.4, "plate_lid", {"N1": "rack1000_lid"}, False),
    ("13:56 plate onto the BioShake at Z88", "BS", 87.9, 180, 82.4, "plate_lid", {"N1": "rack1000_lid"}, False),
]  # fmt: skip


def _event_obstacles(site: str, layout: dict) -> list[rc.Box]:
    # the fixed objects as in the model the events were checked with (its own nests, no front right row)
    out = [b for b in GEO.fixed() if not b.name.startswith("7 mm nest") and "front right" not in b.name]
    for name in ("Regrip", "N1", "N2", "N3", "N4", "N5", "N6", "N7"):
        x, y = XY[name]
        out.append(rc.Box(x - 68.6, x + 68.6, y - 47.5, y + 47.5, 0, 7, f"nest {name}"))
    for name, what in layout.items():
        if name != site:
            x, y = XY[name]
            out.append(rc.Box(x - 63.9, x + 63.9, y - 42.7, y + 42.7, 7, TOP[what], f"{what} at {name}"))
    return out


@pytest.mark.parametrize(("name", "site", "z", "c", "g", "carry", "layout", "hit"), EVENTS, ids=[e[0] for e in EVENTS])
def test_the_model_reproduces_the_real_events(name, site, z, c, g, carry, layout, hit):
    x, y = XY[site]
    exclude = {"BioShake"} if site == "BS" else {f"nest {site}"}
    below, above = CARRY[carry]
    w = rc.vertical_check(
        GEO, x, y, z, z + 60, c, g, {"below": below, "above": above}, _event_obstacles(site, layout), exclude
    )
    if hit:
        assert w.gap is not None and w.gap < 0, (w.gap, w.part, w.obstacle)
    else:
        assert w.gap is None or w.gap > 0, (w.gap, w.part, w.obstacle)


def test_the_hit_of_16_51_is_the_gripper_block_over_the_lidded_rack():
    name, site, z, c, g, carry, layout, _ = EVENTS[0]
    w = rc.vertical_check(GEO, *XY[site], z, 150, c, g, {"below": 3, "above": 6}, _event_obstacles(site, layout))
    assert w.part == "gripper block" and w.obstacle == "rack1000_lid at N5"
    assert w.gap == pytest.approx(-55.4, abs=0.1) and w.tcp_z == pytest.approx(14.7)


def test_the_closest_clear_event_had_3_mm():
    _, site, z, c, g, carry, layout, _ = EVENTS[2]
    obstacles = _event_obstacles(site, layout)
    w = rc.vertical_check(GEO, *XY[site], z, z + 60, c, g, {"below": 2, "above": 12}, obstacles, {"nest Regrip"})
    assert w.gap == pytest.approx(3.0, abs=0.05) and w.part == "gripper block" and "trough_lid" in w.obstacle


# ---- geometry
def _part(boxes, name):
    return [b for b in boxes if b.name == name]


def test_c180_puts_the_rga_body_to_plus_x():
    boxes = rc.rga_boxes(GEO, 834.25, 277.0, 180, 89.5)
    [rotator] = _part(boxes, "rotator")
    assert (rotator.x0, rotator.x1) == pytest.approx((834.25 + 114.6, 834.25 + 190.4))
    assert (rotator.y0, rotator.y1) == pytest.approx((277 - 59.5, 277 + 59.5))
    [pillar] = _part(boxes, "pillar")
    assert (pillar.x0 + pillar.x1) / 2 == pytest.approx(834.25 + 152.5)  # the rotation axis
    blocks = _part(boxes, "gripper block")
    assert min(b.y0 for b in blocks) == pytest.approx(277 - 68.9) and max(b.y1 for b in blocks) == pytest.approx(
        277 + 68.9
    )


def test_c90_puts_the_rga_body_to_minus_y():
    boxes = rc.rga_boxes(GEO, 834.25, 469.3, 90, 131.8)
    [rotator] = _part(boxes, "rotator")
    assert (rotator.y0, rotator.y1) == pytest.approx((469.3 - 190.4, 469.3 - 114.6))
    assert (rotator.x0, rotator.x1) == pytest.approx((834.25 - 59.5, 834.25 + 59.5))
    [pillar] = _part(boxes, "pillar")
    assert (pillar.x0 + pillar.x1) / 2 == pytest.approx(834.25)
    fingers = _part(boxes, "finger")
    assert sorted((f.x0 + f.x1) / 2 for f in fingers) == pytest.approx([834.25 - 65.9, 834.25 + 65.9])


def test_the_gripper_width_moves_fingers_and_blocks_apart():
    def reach(g):
        return max(b.y1 for b in rc.rga_boxes(GEO, 0, 0, 180, g) if b.name in ("finger", "gripper block")) - 0

    assert reach(89.5) - reach(82.4) == pytest.approx((89.5 - 82.4) / 2)
    tips = _part(rc.rga_boxes(GEO, 0, 0, 180, 82.4), "finger tip")
    assert sorted((t.y0 + t.y1) / 2 for t in tips) == pytest.approx([-41.2, 41.2])


def test_sweep_gap_takes_the_closest_height_of_the_vertical_move():
    part = rc.Box(0, 10, 0, 10, 5, 8, "p")  # 5..8 mm above the TCP
    below = rc.Box(0, 10, 0, 10, 0, 20, "below")
    assert rc.sweep_gap(part, 30, 150, below) == (15, 30)  # lowest point counts
    above = rc.Box(0, 10, 0, 10, 200, 300, "above")
    assert rc.sweep_gap(part, 30, 150, above) == (42, 150)  # highest point counts
    gap, _ = rc.sweep_gap(part, 0, 150, rc.Box(0, 10, 0, 10, 50, 60, "in between"))
    assert gap < 0  # passes through it
    assert rc.sweep_gap(part, 0, 150, rc.Box(11, 20, 0, 10, 0, 1000, "beside")) is None


# ---- transfers against a deck
def _deck(**extra) -> dict:
    """The colour-water deck of 2026-11-18 16:51: plate B (lidded) on N2, the lidded trough on N3, the lidded 1000 ul
    rack on N5."""
    base = {
        "PlateB[001]": {"type": "96 Well Flat_Custom", "location": "Nest7mm_Pos", "site": 2},
        "PlateB_Lid[001]": {"type": "Lid", "location": "96Microplate_CoverSite_4", "site": 1, "on": "PlateB[001]"},
        "Trough[001]": {"type": "4 Well SBS Trough", "location": "Nest7mm_Pos", "site": 3},
        "TroughLid[001]": {"type": "Lid", "location": "96Deepwell2ml_CoverSite_5", "site": 1, "on": "Trough[001]"},
        "Rack1000[001]": {"type": "FCA, 1000ul SBS", "location": "Nest7mm_Pos", "site": 5},
        "Rack1000_Lid[001]": {"type": "Lid", "location": "FCA1000ulSBS_CoverSite", "site": 1, "on": "Rack1000[001]"},
        "Rack200_Lid[001]": {"type": "Lid", "location": "FCA200ulSBS_CoverSite", "site": 1, "on": "Rack200[001]"},
        "Rack200[001]": {"type": "FCA, 200ul SBS", "location": "Nest61mm_Pos_1", "site": 1},
    }
    base.update(extra)
    return base


def test_the_lid_move_of_16_51_is_refused():
    snap = rc.snapshot(_deck())
    r = rc.check_transfer(GEO, snap, "PlateB_Lid[001]", rc.Destination("HotelMP_Pos", 3), 5.0)
    assert r.verdict == "collision"
    [text] = r.collisions
    assert "source Nest7mm_Pos[2]" in text and "gripper block" in text and "Rack1000[001] at Nest7mm_Pos[5]" in text
    assert "mm into it" in text
    assert [e.modelled for e in r.ends] == [True, False]  # the hotel is not modelled
    assert "REFUSED" in r.summary()


def test_the_same_lid_move_is_clear_with_the_rack_elsewhere():
    deck = _deck()
    deck["Rack1000[001]"] = {**deck["Rack1000[001]"], "site": 1}  # in line with N2, not over the right column
    r = rc.check_transfer(GEO, rc.snapshot(deck), "PlateB_Lid[001]", rc.Destination("HotelMP_Pos", 3), 5.0)
    assert r.verdict == "ok", r.summary()
    [src, dst] = r.ends
    assert src.grip_z == 14.7 and src.worst.gap > 5 and not dst.modelled
    r7 = rc.check_transfer(GEO, rc.snapshot({**deck, "Rack1000[001]": {**deck["Rack1000[001]"], "site": 7}}),
                           "PlateB_Lid[001]", rc.Destination("HotelMP_Pos", 3), 5.0)  # fmt: skip
    assert r7.verdict == "collision"  # the gripper blocks reach the front right neighbour N7 as well
    assert "OK, smallest gap" in r.summary() and "not modelled: destination HotelMP_Pos[3]" in r.summary()


def test_the_deck_state_and_the_run_change_the_deck():
    deck_entries = {
        "Rack1000[001]": {"type": "FCA, 1000ul SBS", "location": "Nest7mm_Pos", "site": 7, "base": None},
        "TroughLid[001]": {"type": "Lid", "location": None, "site": None},  # taken off the deck
    }
    overlay = {"Extra[001]": rc.Item("96 Well Flat_Custom", "Nest7mm_Pos", 1)}
    snap = rc.snapshot(_deck(), deck_entries, overlay)
    assert snap.items["Rack1000[001]"].site == 7 and "TroughLid[001]" not in snap.items
    assert rc.resolve(GEO, snap, "Rack1000_Lid[001]")[0].name == "Nest7mm_Pos[7]"  # the lid went with its rack
    boxes, not_modelled = rc.obstacles(GEO, snap)
    [trough] = [b for b in boxes if b.name.startswith("Trough[001]")]
    assert trough.z1 == pytest.approx(7 + 41)  # no lid any more
    [rack] = [b for b in boxes if b.name.startswith("Rack1000[001]")]
    assert rack.z1 == pytest.approx(116)
    assert "Rack200[001] at Nest61mm_Pos_1[1]" in not_modelled


def test_a_transfer_that_cannot_be_checked_says_why():
    snap = rc.snapshot(_deck())
    r = rc.check_transfer(GEO, snap, "PlateB[001]", rc.Destination("ODTC_96_Pos", 1), 5.0)
    assert r.verdict == "unknown" and "destination ODTC_96_Pos[1]" in r.unknown[0]
    r = rc.check_transfer(GEO, snap, "Rack200_Lid[001]", rc.Destination("Nest7mm_Pos", 4), 5.0)
    assert r.verdict == "unknown" and "source FCA200ulSBS_CoverSite[1]" in r.unknown[0]
    r = rc.check_transfer(GEO, snap, "Nothing[001]", rc.Destination("Nest7mm_Pos", 4), 5.0)
    assert r.verdict == "unknown" and "not on the deck" in r.unknown[0]
    snap.items["Odd[001]"] = rc.Item("Some Odd Labware", "Nest7mm_Pos", 1)
    r = rc.check_transfer(GEO, snap, "Odd[001]", rc.Destination("Nest7mm_Pos", 4), 5.0)
    assert r.verdict == "unknown" and "type 'Some Odd Labware'" in r.unknown[0]
    # the trough itself has no grip height in the table
    r = rc.check_transfer(GEO, rc.snapshot(_deck()), "Trough[001]", rc.Destination("Nest7mm_Pos", 4), 5.0)
    assert r.verdict == "unknown" and "no NARROW grip height for a trough" in r.unknown[0]


def test_an_obstacle_of_unknown_type_next_to_the_descent_cannot_be_checked():
    deck = _deck(**{"Mystery[001]": {"type": "Mystery Box", "location": "Nest7mm_Pos", "site": 6}})
    deck["Rack1000[001]"] = {**deck["Rack1000[001]"], "site": 1}
    r = rc.check_transfer(GEO, rc.snapshot(deck), "PlateB_Lid[001]", rc.Destination("HotelMP_Pos", 3), 5.0)
    assert r.verdict == "unknown" and "Mystery[001] at Nest7mm_Pos[6]" in r.unknown[0]


def test_wide_grip_for_the_reader():
    deck = {
        "Plate[001]": {"type": "96 Well Flat_Custom", "location": "Regrip_Pos", "site": 1},
        "Rack1000[001]": {"type": "FCA, 1000ul SBS", "location": "Nest7mm_Pos", "site": 1},
    }
    r = rc.check_transfer(GEO, rc.snapshot(deck), "Plate[001]", rc.Destination("InfiniteM200_New", 1), 5.0)
    assert r.mode == "WIDE" and r.verdict == "collision"
    assert r.ends[0].grip_z == 9.1 and r.ends[0].grip_status == "assumed" and not r.ends[1].modelled
    # C=90: the RGA body is to -Y, over N1 (the rack) and N2; with the assumed grip height the gripper block also
    # reaches over the CPLC (slot 2) by about 10 mm in X: not verified on the instrument (README)
    w = rc.vertical_check(GEO, 834.25, 469.3, 9.1, 150, 90, 131.8, None, rc.obstacles(GEO, rc.snapshot(deck))[0])
    assert w.gap < 0
    text = " ".join(r.collisions)
    assert "(assumed)" in text and "Regrip_Pos[1]" in text


def test_a_short_sequence_of_planned_moves():
    deck = _deck()
    deck["Rack1000[001]"] = {**deck["Rack1000[001]"], "site": 1}
    moves = [
        "PlateB_Lid[001]: 96Microplate_CoverSite_4[1] -> HotelMP_Pos[3]",
        "Rack1000_Lid[001] -> Nest7mm_Pos[7]",
        "PlateB[001] -> Nest7mm_Pos[6]",
        "PlateB[001] -> Nest7mm_Pos[2]",
        "PlateB_Lid[001] -> lid of PlateB[001]",
        "Rack1000_Lid[001] -> base",
        "Plate_A[001] (96 Well Flat_Custom): Nest7mm_Pos[5] -> Regrip_Pos[1]",
        "nonsense",
    ]
    results = rc.check_moves(GEO, rc.snapshot(deck), moves, 5.0)
    assert [r.verdict for r in results] == ["ok", "ok", "ok", "ok", "ok", "ok", "ok", "unknown"], [
        r.summary() for r in results
    ]
    assert results[4].destination == "lid of PlateB[001] at Nest7mm_Pos[2]"
    assert results[4].ends[1].grip_z == 14.7
    assert results[5].ends[0].grip_z == 10.1 and results[5].ends[1].grip_z == 104.1
    assert "not on the deck" in results[6].notes[0]


def test_a_planned_move_is_checked_against_the_deck_the_moves_before_it_leave():
    deck = _deck()
    deck["Rack1000[001]"] = {**deck["Rack1000[001]"], "site": 1}
    # the rack is taken as standing on N5: the lid of plate B then collides as at 16:51
    moves = ["Rack1000[001] (FCA, 1000ul SBS): Nest7mm_Pos[5] -> Nest7mm_Pos[5]", "PlateB_Lid[001] -> HotelMP_Pos[3]"]
    first, second = rc.check_moves(GEO, rc.snapshot(deck), moves, 5.0)
    assert "the deck has Rack1000[001] at Nest7mm_Pos[1]" in first.notes[0]
    assert second.verdict == "collision"


def test_statements_are_parsed_and_applied():
    from unitelabs.tecan_fluent.io.fluent.gripper.statements import (
        add_labware_xml,
        lid_on_xml,
        remove_labware_xml,
        to_base_xml,
        transfer_xml,
    )

    assert rc.rga_transfer(transfer_xml("P[001]", "Regrip_Pos", 1)) == ("P[001]", rc.Destination("Regrip_Pos", 1))
    assert rc.rga_transfer(to_base_xml("P[001]")) == ("P[001]", rc.Destination(base=True))
    assert rc.rga_transfer(lid_on_xml("L[001]", "P[001]")) == ("L[001]", rc.Destination(onto="P[001]"))
    assert rc.rga_transfer(add_labware_xml("T", "X[001]", "Nest7mm_Pos", 1)) is None
    snap = rc.snapshot({})
    rc.apply_statement(snap, add_labware_xml("96 Well Flat_Custom", "X[001]", "Nest7mm_Pos", 4))
    assert snap.items["X[001]"] == rc.Item("96 Well Flat_Custom", "Nest7mm_Pos", 4)
    steps = [("m", transfer_xml("X[001]", "Regrip_Pos", 1)), ("m", transfer_xml("X[001]", "InfiniteM200_New", 1))]
    results = rc.check_steps(GEO, snap, steps, 5.0)
    assert [r.source for r in results] == ["Nest7mm_Pos[4]", "Regrip_Pos[1]"]  # the second starts where the first ends
    assert snap.items["X[001]"].location == "Nest7mm_Pos"  # check_steps leaves the snapshot alone
    rc.apply_statement(snap, remove_labware_xml("X[001]"))
    assert "X[001]" not in snap.items


def test_offline_command_line(tmp_path, capsys):
    import json

    layout = tmp_path / "layout.json"
    layout.write_text(json.dumps(_deck()))
    moves = tmp_path / "moves.txt"
    moves.write_text("PlateB_Lid[001] -> HotelMP_Pos[3]\n")
    assert rc.main([str(layout), str(moves)]) == 1
    assert "1. PlateB_Lid[001]" in capsys.readouterr().out
