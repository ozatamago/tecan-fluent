"""The deck state (io/fluent/deck/state.py) and its registration at the start of a run. Nothing is sent: the
definitions come from a fake definition index, runs are dry runs."""

import asyncio
import datetime
import json
import os

import pytest

from unitelabs.tecan_fluent.io.fluent.deck.state import DeckConfig, DeckState
from unitelabs.tecan_fluent.io.fluent.gripper.labware_tracker import LabwareTracker, PlateTransferConfig
from unitelabs.tecan_fluent.io.fluent.gripper.statements import add_labware_xml, remove_labware_xml
from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError, FluentBackendConfig, FluentControlBackend
from unitelabs.tecan_fluent.io.fluentcontrol.definitions import DefinitionCheckFailed, DefinitionView

WORKTABLE = "WT_TEST"
PLATE = "96 Well Flat_Custom[001]"
RACK = "FCA_ 200ul SBS[001]"


def view() -> DefinitionView:
    """A fake definition index: two labware types, three locations, two labware on the base worktable."""
    return DefinitionView(
        worktable=WORKTABLE,
        labware_types={"96 Well Flat_Custom", "FCA, 200ul SBS", "96 Well Skirted PCR_Custom"},
        sites={"Nest7mm_Pos": 8, "Regrip_Pos": 1, "HotelMP_Pos": 4},
        labware={
            PLATE: {"type": "96 Well Flat_Custom", "location": "Nest7mm_Pos", "site": 6},
            RACK: {"type": "FCA, 200ul SBS", "location": "Nest7mm_Pos", "site": 2},
        },
    )


class Clock:
    def __init__(self):
        self.now = datetime.datetime(2026, 10, 21, 10, 0, 0)

    def __call__(self):
        return self.now


def deck(tmp_path, records=None, persist=True, legacy_file="", definitions=view, **config) -> DeckState:
    cfg = DeckConfig(state_file=str(tmp_path / "deck.json"), **config)
    return DeckState(
        cfg,
        WORKTABLE,
        persist=persist,
        definitions=definitions,
        recorder=(lambda rel, data: records.append((rel, data))) if records is not None else None,
        legacy_file=legacy_file,
        legacy_labware=PlateTransferConfig().labware,
        clock=Clock(),
    )


def test_place_move_remove_and_version(tmp_path):
    records = []
    d = deck(tmp_path, records)
    assert d.layout() == [f"base worktable {WORKTABLE}, version 0"]
    assert d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1, "", "Franka") == 1
    assert d.move("Plate_A[001]", "HotelMP_Pos", 3, "Kachaka") == 2
    assert d.move(PLATE, "Regrip_Pos", 1, "a person") == 3  # base-worktable labware moved: now listed
    assert d.remove(RACK, "Franka") == 4  # taken off the deck: listed with location null
    state = json.loads((tmp_path / "deck.json").read_text())
    assert state["version"] == 4 and state["base_worktable"] == WORKTABLE
    assert (
        state["labware"]["Plate_A[001]"]["location"] == "HotelMP_Pos" and state["labware"]["Plate_A[001]"]["site"] == 3
    )
    assert state["labware"]["Plate_A[001]"]["base"] is None
    assert state["labware"][PLATE]["base"] == {"location": "Nest7mm_Pos", "site": 6}
    assert state["labware"][RACK]["location"] is None
    assert d.layout() == [
        f"base worktable {WORKTABLE}, version 4",
        f"{PLATE}: 96 Well Flat_Custom at Regrip_Pos[1] (moved by a person, base Nest7mm_Pos[6])",
        f"{RACK}: FCA, 200ul SBS taken off the deck (removed by Franka, base Nest7mm_Pos[2])",
        "Plate_A[001]: 96 Well Skirted PCR_Custom at HotelMP_Pos[3] "
        "(placed by Franka, moved by Kachaka, not on the base worktable)",
    ]
    # back at its base position, a base-worktable labware is not listed any more; a removed placed labware is gone
    d.move(PLATE, "Nest7mm_Pos", 6, "a person")
    d.remove("Plate_A[001]", "Franka")
    assert set(d.load()["labware"]) == {RACK}
    # every change is recorded under records\deck
    assert [rel.split("_", 1)[1] for rel, _ in records] == [
        "PlaceLabware.json",
        "MoveLabwareRecord.json",
        "MoveLabwareRecord.json",
        "RemoveLabware.json",
        "MoveLabwareRecord.json",
        "RemoveLabware.json",
    ]
    assert all(rel.startswith("deck\\") for rel, _ in records)
    assert records[0][1]["version"] == 1 and records[0][1]["after"]["placed_by"] == "Franka"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("X[001]", "No Such Type", "HotelMP_Pos", 1), "Labware type 'No Such Type' is not defined"),
        (("X[001]", "96 Well Flat_Custom", "Nowhere_Pos", 1), "Location 'Nowhere_Pos' is not on worktable WT_TEST"),
        (("X[001]", "96 Well Flat_Custom", "Regrip_Pos", 2), r"Regrip_Pos\[2\] does not exist"),
        (
            ("X[001]", "96 Well Flat_Custom", "Nest7mm_Pos", 6),
            r"Nest7mm_Pos\[6\] is taken by 96 Well Flat_Custom\[001\]",
        ),
        ((PLATE, "96 Well Flat_Custom", "HotelMP_Pos", 1), "already on the deck at Nest7mm_Pos"),
        ((RACK, "96 Well Flat_Custom", "HotelMP_Pos", 1), "already on the deck"),
    ],
)
def test_place_is_refused_for_taken_sites_and_unknown_types_or_locations(tmp_path, args, message):
    d = deck(tmp_path)
    with pytest.raises(BackendError, match=message):
        d.place(*args)
    assert d.load()["version"] == 0 and not (tmp_path / "deck.json").exists()


def test_a_site_taken_in_the_deck_state_is_refused_and_unknown_labels_too(tmp_path):
    d = deck(tmp_path)
    d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1)
    with pytest.raises(BackendError, match=r"HotelMP_Pos\[1\] is taken by Plate_A\[001\]"):
        d.place("Plate_B[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1)
    with pytest.raises(BackendError, match=r"HotelMP_Pos\[1\] is taken"):
        d.move(PLATE, "HotelMP_Pos", 1)
    with pytest.raises(BackendError, match="neither on the base worktable WT_TEST nor in the deck state"):
        d.remove("Ghost[001]")
    with pytest.raises(BackendError, match="neither on the base worktable"):
        d.move("Ghost[001]", "HotelMP_Pos", 2)
    # a base-worktable labware taken off can be put back, but not as another type
    d.remove(RACK)
    with pytest.raises(BackendError, match="is a FCA, 200ul SBS on the base worktable"):
        d.place(RACK, "96 Well Flat_Custom", "Nest7mm_Pos", 2)
    d.place(RACK, "FCA, 200ul SBS", "Nest7mm_Pos", 2)
    assert RACK not in d.load()["labware"]  # back at base, nothing else recorded


def test_the_file_is_written_atomically(tmp_path, monkeypatch):
    d = deck(tmp_path)
    d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1)
    before = (tmp_path / "deck.json").read_text()

    def broken_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", broken_replace)
    with pytest.raises(OSError, match="disk full"):
        d.move("Plate_A[001]", "HotelMP_Pos", 2)
    assert (tmp_path / "deck.json").read_text() == before  # the old state is intact
    assert [p.name for p in tmp_path.iterdir()] == ["deck.json"]  # and no temporary file is left


def test_a_change_by_someone_else_in_between_is_refused(tmp_path):
    d = deck(tmp_path)
    d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1)
    real_load = d.load

    def load_then_other_writer():
        state = real_load()
        other = json.loads((tmp_path / "deck.json").read_text())
        other["version"] += 1
        (tmp_path / "deck.json").write_text(json.dumps(other))
        return state

    d.load = load_then_other_writer
    with pytest.raises(BackendError, match="changed meanwhile"):
        d.move("Plate_A[001]", "HotelMP_Pos", 2)


def test_contents_and_tip_racks(tmp_path):
    d = deck(tmp_path)
    d.set_contents(PLATE, ["A1", "B1"], "water", [150])
    assert d.entry(PLATE)["contents"] == {
        "A1": {"liquid": "water", "volume_ul": 150},
        "B1": {"liquid": "water", "volume_ul": 150},
    }
    d.set_contents(PLATE, ["A1"], "", [0])
    assert list(d.entry(PLATE)["contents"]) == ["B1"]
    with pytest.raises(BackendError, match="Wells must be names"):
        d.set_contents(PLATE, ["Z"], "water", [1])
    with pytest.raises(BackendError, match="one per well"):
        d.set_contents(PLATE, ["A1", "A2", "A3"], "water", [1, 2])
    # a full rack put in at its base position (refilled in place) and a rack put back as it was
    with pytest.raises(BackendError, match="Kind must be one of 'full', 'as is'"):
        d.place_tip_rack(RACK, "FCA, 200ul SBS", "Nest7mm_Pos", 2, "new", "a person")
    d.place_tip_rack(RACK, "FCA, 200ul SBS", "Nest7mm_Pos", 2, "full", "a person")
    d.place_tip_rack("FCA_ 200ul SBS[002]", "FCA, 200ul SBS", "HotelMP_Pos", 4, "as is", "Franka")
    assert d.tip_racks() == [
        f"{RACK}: FCA, 200ul SBS at Nest7mm_Pos[2] (full since 2026-10-21T10:00:00, registered at the next run start)",
        "FCA_ 200ul SBS[002]: FCA, 200ul SBS at HotelMP_Pos[4] (as is since 2026-10-21T10:00:00)",
    ]


def test_registration_statements_in_order(tmp_path):
    d = deck(tmp_path)
    d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1, "", "Franka")
    d.move(PLATE, "Regrip_Pos", 1)
    d.place_tip_rack(RACK, "FCA, 200ul SBS", "Nest7mm_Pos", 2, "full", "a person")  # refilled in place
    steps, info = d.registration()
    assert steps == [
        (f"RemoveLabware {PLATE} (deck state, bookkeeping only)", remove_labware_xml(PLATE)),
        (f"RemoveLabware {RACK} (deck state, bookkeeping only)", remove_labware_xml(RACK)),
        (
            f"AddLabware {PLATE} at Regrip_Pos[1] (deck state, bookkeeping only)",
            add_labware_xml("96 Well Flat_Custom", PLATE, "Regrip_Pos", 1),
        ),
        (
            f"AddLabware {RACK} at Nest7mm_Pos[2] (deck state, bookkeeping only)",
            add_labware_xml("FCA, 200ul SBS", RACK, "Nest7mm_Pos", 2),
        ),
        (
            "AddLabware Plate_A[001] at HotelMP_Pos[1] (deck state, bookkeeping only)",
            add_labware_xml("96 Well Skirted PCR_Custom", "Plate_A[001]", "HotelMP_Pos", 1),
        ),
    ]
    assert info["version"] == 3 and info["refilled"] == [RACK]
    # once registered, a full rack at its base position is left to FluentControl's own count of used tips
    d.registered(info)
    assert [label for label, _ in d.registration()[0]] == [
        f"RemoveLabware {PLATE} (deck state, bookkeeping only)",
        f"AddLabware {PLATE} at Regrip_Pos[1] (deck state, bookkeeping only)",
        "AddLabware Plate_A[001] at HotelMP_Pos[1] (deck state, bookkeeping only)",
    ]
    # a base-worktable labware taken off is only removed
    d.remove(PLATE)
    assert [label for label, _ in d.registration()[0]][0] == f"RemoveLabware {PLATE} (deck state, bookkeeping only)"
    assert not any(PLATE in label and "AddLabware" in label for label, _ in d.registration()[0])


def test_migration_from_labware_positions(tmp_path):
    old = tmp_path / "labware_positions.json"
    old.write_text(json.dumps({PLATE: ["Regrip_Pos", 1]}))
    # a dry run keeps reading the old file and writes nothing
    dry = deck(tmp_path, persist=False, legacy_file=str(old))
    assert dry.positions() == {PLATE: ["Regrip_Pos", 1]} and not (tmp_path / "deck.json").exists()
    # the first real use takes it over once
    records = []
    live = deck(tmp_path, records, legacy_file=str(old))
    assert live.entry(PLATE)["location"] == "Regrip_Pos"
    state = json.loads((tmp_path / "deck.json").read_text())
    assert state["version"] == 1 and state["migrated_from"] == str(old)
    assert state["labware"][PLATE]["base"] == {"location": "Nest7mm_Pos", "site": 6}
    assert [rel.split("_", 1)[1] for rel, _ in records] == ["Migrate.json"]
    # from then on the deck state is used; the old file is no longer read or written
    old.write_text(json.dumps({PLATE: ["HotelMP_Pos", 1]}))
    assert live.positions() == {PLATE: ["Regrip_Pos", 1]}
    assert json.loads(old.read_text()) == {PLATE: ["HotelMP_Pos", 1]}


def test_tracker_is_a_view_on_the_deck_state(tmp_path):
    d = deck(tmp_path)
    t = LabwareTracker(PlateTransferConfig(positions_file=str(tmp_path / "pos.json")), deck=d)
    # the run start registers the position, so a move is just the RGA statement
    t.record(PLATE, "Regrip_Pos", 1)
    assert d.entry(PLATE)["moved_by"] == "RGA" and t.where(PLATE) == ("Regrip_Pos", 1)
    assert [label for label, _ in t.move_steps(PLATE, "Nest7mm_Pos", 6)] == [f"RGA {PLATE} -> Nest7mm_Pos[6]"]
    assert not (tmp_path / "pos.json").exists()
    t.record(PLATE, "Nest7mm_Pos", 6)
    assert not t.moved_away(PLATE) and d.load()["labware"] == {}
    d.remove(PLATE)
    with pytest.raises(BackendError, match="taken off the deck"):
        t.where(PLATE)


def test_base_worktable_must_be_the_one_of_ofml_apihost(tmp_path):
    d = deck(tmp_path, base_worktable="OFML_480")
    with pytest.raises(BackendError, match="deck.base_worktable 'OFML_480' is not the worktable OFML_ApiHost uses"):
        d.layout()
    (tmp_path / "deck.json").write_text(json.dumps({"labware": {}, "base_worktable": "OFML_480", "version": 3}))
    with pytest.raises(BackendError, match="describes worktable OFML_480, not WT_TEST"):
        deck(tmp_path).layout()


def test_a_dry_run_changes_memory_only_and_works_without_definitions(tmp_path):
    def offline():
        raise DefinitionCheckFailed("offline")

    d = deck(tmp_path, persist=False, definitions=offline)
    d.place("Plate_A[001]", "Anything", "Anywhere", 1)  # not checked in a dry run
    assert d.load()["version"] == 1 and not (tmp_path / "deck.json").exists()
    live = deck(tmp_path, definitions=offline)
    with pytest.raises(BackendError, match="Cannot check the FluentControl definitions"):
        live.place("Plate_A[001]", "Anything", "Anywhere", 1)


# ---- the start of a run (dry run, records kept locally)
def _backend(tmp_path) -> tuple[FluentControlBackend, DeckState]:
    backend = FluentControlBackend(FluentBackendConfig())  # dry run; the Fluent PC is offline in tests
    d = deck(tmp_path, persist=False, records=None)
    d.recorder = backend.write_record
    backend.attach_deck(d)
    return backend, d


def _steps(record_dir) -> list[str]:
    return sorted(p.name for p in (record_dir / "steps").iterdir())


def test_start_run_registers_the_deck_state_first_and_records_it(tmp_path):
    backend, d = _backend(tmp_path)
    d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1, "", "Franka")
    d.move(PLATE, "Regrip_Pos", 1)

    async def scenario():
        import pathlib

        folder = pathlib.Path(await backend.start_run())
        await backend.run_macro("SiLA-ODTC_OpenDoor")
        assert await backend.end_run() == 1  # the registration is not one of the commands
        return folder

    folder = asyncio.run(scenario())
    first, second = sorted(p for p in folder.iterdir() if p.is_dir())
    assert "Deck_registration_at_run_start" in first.name and "OpenDoor" in second.name
    # the exact statements, in order: remove what was moved, then add everything at its recorded position
    assert [(first / "steps" / name).read_text() for name in _steps(first)] == [
        remove_labware_xml(PLATE),
        add_labware_xml("96 Well Flat_Custom", PLATE, "Regrip_Pos", 1),
        add_labware_xml("96 Well Skirted PCR_Custom", "Plate_A[001]", "HotelMP_Pos", 1),
    ]
    assert [name[:20] for name in _steps(first)] == [
        "01_RemoveLabware_96_",
        "02_AddLabware_96_Wel",
        "03_AddLabware_Plate_",
    ]
    manifest = json.loads((first / "manifest.json").read_text())
    assert manifest["deck"]["version"] == 2 and manifest["deck"]["added"] == {
        PLATE: "96 Well Flat_Custom",
        "Plate_A[001]": "96 Well Skirted PCR_Custom",
    }
    assert json.loads((first / "result.json").read_text())["status"] == "ok"


def test_a_command_with_a_run_of_its_own_registers_the_deck_state_too(tmp_path):
    backend, d = _backend(tmp_path)
    asyncio.run(backend.run_macro("SiLA-ODTC_OpenDoor"))  # nothing to register: no extra record
    runs = tmp_path / ".riken_fluent780" / "dry-run" / "runs"
    assert len(list(runs.iterdir())) == 1
    d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1)
    asyncio.run(backend.run_macro("SiLA-ODTC_CloseDoor"))
    names = sorted(p.name for p in runs.iterdir())
    assert len(names) == 3 and "Deck_registration" in names[1] and "CloseDoor" in names[2]


def test_deck_changes_are_recorded_with_the_backend(tmp_path):
    backend, d = _backend(tmp_path)
    d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1, "", "Franka")
    [record] = list((tmp_path / ".riken_fluent780" / "dry-run" / "deck").iterdir())
    assert record.name.endswith("_PlaceLabware.json") and json.loads(record.read_text())["version"] == 1


def test_labels_neither_on_the_worktable_nor_in_the_deck_state_are_refused(tmp_path):
    d = deck(tmp_path)
    d.place("Plate_A[001]", "96 Well Skirted PCR_Custom", "HotelMP_Pos", 1)
    d.remove(RACK)
    base = {PLATE, RACK}
    from unitelabs.tecan_fluent.io.fluent.gripper.statements import transfer_xml

    ok, info = d.check_labels([("move", transfer_xml("Plate_A[001]", "Regrip_Pos", 1))], base)
    assert ok == [] and info["version"] == 2
    problems, _ = d.check_labels([("move", transfer_xml("Ghost[001]", "Regrip_Pos", 1))], base)
    assert problems == ["Labware 'Ghost[001]' is neither on the base worktable WT_TEST nor in the deck state"]
    problems, _ = d.check_labels([("move", transfer_xml(RACK, "Regrip_Pos", 1))], base)
    assert problems and "recorded as taken off the deck" in problems[0]
    # RemoveLabware of a removed labware (the registration), labware added in the same steps or in the open run
    assert d.check_labels([("rm", remove_labware_xml(RACK))], base)[0] == []
    steps = [
        ("add", add_labware_xml("96 Well Flat_Custom", "Temp[001]", "HotelMP_Pos", 2)),
        ("move", transfer_xml("Temp[001]", "Regrip_Pos", 1)),
    ]
    assert d.check_labels(steps, base)[0] == []
    assert d.check_labels([("move", transfer_xml("Session[001]", "Regrip_Pos", 1))], base, {"Session[001]"})[0] == []
