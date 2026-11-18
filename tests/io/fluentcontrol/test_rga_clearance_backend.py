"""Every RGA transfer is checked for collisions before anything is sent (io/fluent/rga_clearance.py, wired into the
backend): the RGA commands of Labware, PlateTransfer and PlateHandling are refused with their own errors, unknown
sites are refused by default, and Deck.CheckRgaMoves checks a planned sequence. Nothing reaches FluentControl."""

import asyncio

import pytest

from unitelabs.tecan_fluent.apps.fluent780_all import Fluent780AllConnectorConfig, build_features
from unitelabs.tecan_fluent.features.fluent.gripper.labware import LabwareCommandFailed
from unitelabs.tecan_fluent.features.fluent.gripper.plate_transfer import PlateTransferFailed
from unitelabs.tecan_fluent.features.infinite.errors import ReaderOperationFailed
from unitelabs.tecan_fluent.io.fluent import rga_clearance as rc
from unitelabs.tecan_fluent.io.fluent.gripper.labware_tracker import PlateTransferConfig
from unitelabs.tecan_fluent.io.fluent.gripper.statements import add_labware_xml, transfer_xml
from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError, FluentBackendConfig, FluentControlBackend
from unitelabs.tecan_fluent.io.fluentcontrol.definitions import DefinitionCheckFailed, DefinitionView

FLAT = "96 Well Flat_Custom[001]"


def deck(**changes) -> dict:
    """The deck of 2026-11-18 16:51: plate B with its lid on N2, the lidded 1000 ul rack on N5."""
    labware = {
        "PlateB[001]": {"type": "96 Well Flat_Custom", "location": "Nest7mm_Pos", "site": 2, "on": ""},
        "PlateB_Lid[001]": {"type": "Lid", "location": "96Microplate_CoverSite_4", "site": 1, "on": "PlateB[001]"},
        "Rack1000[001]": {"type": "FCA, 1000ul SBS", "location": "Nest7mm_Pos", "site": 5, "on": ""},
        "Rack1000_Lid[001]": {"type": "Lid", "location": "FCA1000ulSBS_CoverSite", "site": 1, "on": "Rack1000[001]"},
    }
    for label, entry in changes.items():
        if entry is None:
            labware.pop(label)
        else:
            labware[label] = {**labware.get(label, {"on": ""}), **entry}
    return labware


def view(labware: dict) -> DefinitionView:
    return DefinitionView("WT2411004293_Ver.0.5_OFML", set(), {}, labware)


class _Channel:
    def __init__(self):
        self.sent = []

    def ExecuteCommand(self, xml):  # noqa: N802 - name of the UniteLabs connector's command
        self.sent.append(xml)


class _Client:
    """Only records commands; any other call (starting a run, reading the state) fails the test."""

    def __init__(self):
        self.ExecutionChannelController = _Channel()

    def __getattr__(self, name):
        raise AssertionError(f"{name} must not be used: the operation should have been refused first")


def _live(backend: FluentControlBackend, labware: dict) -> list:
    """Make the backend look live (not a dry run) with the given deck; returns the list of records written."""
    backend.config.dry_run = False
    backend.preflight.dry_run = False
    backend._client = _Client()
    backend.preflight.definition_view = lambda: view(labware)
    records = []
    backend.write_record = lambda rel, data: records.append((rel, data))
    return records


def sent(backend) -> list:
    return backend._client.ExecutionChannelController.sent


class _Status:
    def update(self, *a, **k):
        pass


STATUS = _Status()


def test_the_lid_move_of_16_51_is_refused_before_anything_is_sent():
    backend = FluentControlBackend(FluentBackendConfig())
    records = _live(backend, deck())
    step = ("RGA PlateB_Lid[001] -> HotelMP_Pos[3]", transfer_xml("PlateB_Lid[001]", "HotelMP_Pos", 3))
    with pytest.raises(BackendError) as caught:
        backend._run_steps([step], lambda _: None)
    text = str(caught.value)
    assert "Refused by the RGA clearance check, nothing was sent" in text
    assert "gripper block" in text and "Rack1000[001] at Nest7mm_Pos[5]" in text and "Nest7mm_Pos[2]" in text
    assert sent(backend) == []
    [(rel, data)] = records
    assert rel.startswith("rga_clearance\\") and rel.endswith("_refused.json")
    assert data["transfers"][0]["verdict"] == "collision" and data["transfers"][0]["ends"][0]["part"] == "gripper block"


def test_the_check_goes_into_the_record_of_an_operation():
    backend = FluentControlBackend(FluentBackendConfig())
    _live(backend, deck(**{"Rack1000[001]": {"site": 1}}))
    step = ("RGA PlateB_Lid[001] -> HotelMP_Pos[3]", transfer_xml("PlateB_Lid[001]", "HotelMP_Pos", 3))
    record = backend._check_clearance([step], "x")
    assert record["checked"] is True and record["margin_mm"] == 2.5
    [transfer] = record["transfers"]
    assert transfer["verdict"] == "ok" and transfer["ends"][0]["gap_mm"] > 5
    assert backend._check_clearance([("other", add_labware_xml("T", "X[001]", "Nest7mm_Pos", 1))], "x") is None


def _features(tmp_path, labware: dict):
    config = Fluent780AllConnectorConfig()
    config.plates = PlateTransferConfig(positions_file=str(tmp_path / "labware_positions.json"))
    features = {type(x).__name__: x for x in build_features(config)}
    backend = features["PlateTransfer"].backend
    return features, backend, _live(backend, labware)


def test_plate_transfer_is_refused_with_its_own_error(tmp_path):
    # the lidded rack on N4: the RGA body is over it when the plate goes down onto the regrip position
    flat = {"type": "96 Well Flat_Custom", "location": "Nest7mm_Pos", "site": 6}  # base of plates.labware
    f, backend, _ = _features(tmp_path, deck(**{"Rack1000[001]": {"site": 4}, FLAT: flat}))
    with pytest.raises(
        PlateTransferFailed,
        match=r"at the destination Regrip_Pos\[1\] the RGA's finger web .* Rack1000\[001\] at Nest7mm_Pos\[4\]",
    ):
        asyncio.run(f["PlateTransfer"].move_labware(FLAT, "Regrip_Pos", 1, status=STATUS))
    assert sent(backend) == []


def test_labware_commands_are_refused_with_their_own_error(tmp_path):
    f, backend, _ = _features(tmp_path, deck())
    backend._session = {"rel": "runs\\x_session", "started": "x", "commands": 0}  # a run is open
    with pytest.raises(LabwareCommandFailed, match="gripper block"):
        asyncio.run(f["Labware"].transfer_labware("PlateB_Lid[001]", "HotelMP_Pos", 3, status=STATUS))
    # the lid was taken off in this run (by hand here): putting it back on is checked at the plate
    backend.run_labware["PlateB_Lid[001]"] = rc.Item("Lid", "HotelMP_Pos", 3)
    with pytest.raises(LabwareCommandFailed, match=r"destination Nest7mm_Pos\[2\]"):
        asyncio.run(f["Labware"].put_lid_on("PlateB_Lid[001]", "PlateB[001]", status=STATUS))
    with pytest.raises(LabwareCommandFailed, match="gripper block"):
        asyncio.run(f["Labware"].move_labware_to_base("PlateB_Lid[001]", status=STATUS))
    assert sent(backend) == []


def test_measuring_a_worktable_plate_is_refused_with_its_own_error(tmp_path):
    # the lidded rack on N1: under the RGA body when the WIDE grip goes down at the regrip position (C=90)
    flat = {"type": "96 Well Flat_Custom", "location": "Nest7mm_Pos", "site": 6}
    f, backend, _ = _features(tmp_path, deck(**{FLAT: flat, "Rack1000[001]": {"site": 1}}))
    reader = f["PlateHandling"].reader

    async def method_found(_method):
        return None

    reader.check_method = method_found
    with pytest.raises(ReaderOperationFailed, match=r"Regrip_Pos\[1\]") as caught:
        asyncio.run(f["PlateHandling"].measure_worktable_plate(FLAT, "OFML_Abs405.mth", status=STATUS))
    assert "Rack1000[001] at Nest7mm_Pos[1]" in str(caught.value) and "(derived)" in str(caught.value)
    assert sent(backend) == []


def test_a_reader_transfer_passes_with_the_cplc_exception_recorded():
    backend = FluentControlBackend(FluentBackendConfig())
    flat = {"type": "96 Well Flat_Custom", "location": "Regrip_Pos", "site": 1}
    _live(backend, deck(**{FLAT: flat, "Rack1000[001]": {"site": 7}}))
    record = backend._check_clearance([("RGA", transfer_xml(FLAT, "InfiniteM200_New", 1))], "x")
    [transfer] = record["transfers"]
    assert transfer["verdict"] == "ok"
    [applied] = transfer["ends"][0]["exceptions_applied"]
    assert applied["obstacle"] == "CPLC 2 (Inheco CPLC Flat)" and "exception applied" in transfer["notes"][0]


def test_a_transfer_to_a_site_not_in_the_table_is_refused_unless_set_to_warn():
    backend = FluentControlBackend(FluentBackendConfig())
    _live(backend, deck())
    step = ("RGA", transfer_xml("PlateB[001]", "Alpaqua_Magnum_FLX_Pos", 1))
    with pytest.raises(BackendError, match=r"cannot check .*destination Alpaqua_Magnum_FLX_Pos\[1\]"):
        backend._run_steps([step], lambda _: None)
    assert sent(backend) == []
    backend.config.rga_clearance.unknown = "warn"
    record = backend._check_clearance([step], "x")
    assert record["transfers"][0]["verdict"] == "unknown"
    backend.config.rga_clearance.unknown = "nonsense"
    with pytest.raises(BackendError, match="must be one of"):
        backend._check_clearance([step], "x")


def test_a_deck_that_cannot_be_read_refuses_live_and_is_noted_in_a_dry_run():
    backend = FluentControlBackend(FluentBackendConfig())
    _live(backend, deck())

    def offline():
        raise DefinitionCheckFailed("offline")

    backend.preflight.definition_view = offline
    step = ("RGA", transfer_xml(FLAT, "Regrip_Pos", 1))
    with pytest.raises(BackendError, match="could not be checked for collisions"):
        backend._run_steps([step], lambda _: None)
    assert sent(backend) == []
    backend.config.dry_run = True
    record = backend._check_clearance([step], "x")
    assert record["checked"] is False and "offline" in record["reason"]


def test_another_worktable_is_not_checked_with_this_table():
    backend = FluentControlBackend(FluentBackendConfig())
    _live(backend, deck())
    backend.config.definitions.workspace = "Fluent480_Worktable"
    with pytest.raises(BackendError, match="describes the deck of worktable WT2411004293_Ver.0.5_OFML"):
        backend._run_steps([("RGA", transfer_xml("PlateB[001]", "Nest7mm_Pos", 1))], lambda _: None)
    assert sent(backend) == []


def test_the_check_can_be_turned_off():
    backend = FluentControlBackend(FluentBackendConfig())
    _live(backend, deck())
    backend.config.rga_clearance.enabled = False
    assert backend._check_clearance([("RGA", transfer_xml("PlateB_Lid[001]", "HotelMP_Pos", 3))], "x") is None


def test_in_an_open_run_the_check_follows_what_the_run_did():
    backend = FluentControlBackend(FluentBackendConfig())  # dry run: nothing is sent anywhere
    backend.preflight.definition_view = lambda: view(deck(**{"Rack1000[001]": None, "Rack1000_Lid[001]": None}))

    async def scenario():
        await backend.start_run()
        # a lidded 1000 ul rack is added on N5 in this run: from then on the lid of plate B cannot be taken off
        await backend.run_steps(
            [
                ("AddLabware rack", add_labware_xml("FCA, 1000ul SBS", "R[001]", "Nest7mm_Pos", 5)),
                ("AddLabware lid", add_labware_xml("Lid", "Rack1000_Lid[002]", "Nest7mm_Pos", 3)),
                ("RGA lid", transfer_xml("Rack1000_Lid[002]", "Nest7mm_Pos", 7)),
            ]
        )
        assert backend.run_labware["R[001]"] == rc.Item("FCA, 1000ul SBS", "Nest7mm_Pos", 5)
        assert backend.run_labware["Rack1000_Lid[002]"].site == 7
        with pytest.raises(BackendError, match=r"R\[001\] at Nest7mm_Pos\[5\]"):
            await backend.run_steps([("RGA", transfer_xml("PlateB_Lid[001]", "HotelMP_Pos", 3))])
        await backend.end_run()
        assert backend.run_labware == {}

    asyncio.run(scenario())


def test_deck_check_rga_moves(tmp_path):
    config = Fluent780AllConnectorConfig()  # dry run; needs no FluentControl
    f = {type(x).__name__: x for x in build_features(config)}
    f["Deck"].backend.preflight.definition_view = lambda: view(deck())
    out = asyncio.run(
        f["Deck"].check_rga_moves(
            [
                "PlateB_Lid[001]: 96Microplate_CoverSite_4[1] -> HotelMP_Pos[3]",
                "Rack1000[001] (FCA, 1000ul SBS): Nest7mm_Pos[1] -> Nest7mm_Pos[1]",
                "PlateB_Lid[001] -> lid of PlateB[001]",
                "PlateB[001] -> Alpaqua_Magnum_FLX_Pos[1]",
            ]
        )
    )
    assert out[0].startswith("1. PlateB_Lid[001]") and "REFUSED" in out[0] and "gripper block" in out[0]
    assert "note: the deck has Rack1000[001] at Nest7mm_Pos[5]" in out[1]
    assert out[2].startswith("3.") and ": OK, smallest gap" in out[2]
    assert "NOT CHECKED" in out[3] and "Alpaqua_Magnum_FLX_Pos[1]" in out[3]
