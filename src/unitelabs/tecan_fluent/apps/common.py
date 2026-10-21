"""Parts shared by the server assemblies. No config class here (the UniteLabs CDK allows one per process)."""

from unitelabs.cdk import SiLAServerConfig

from .. import __version__
from ..io.fluent.camera.deck_cameras import DeckCameraConfig, DeckCameras
from ..io.fluent.deck.state import DeckConfig, DeckState
from ..io.fluent.gripper.labware_tracker import LabwareTracker, PlateTransferConfig
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from ..io.fluentcontrol.definitions import FluentPc
from ..io.fluentcontrol.hands_off import HandsOff


def sila_server(name: str, type_: str, description: str, uuid: str, port: int) -> SiLAServerConfig:
    """The default SiLA server settings of one assembly (fixed UUID and port, so each server keeps its identity)."""
    return SiLAServerConfig(
        uuid=uuid,
        name=name,
        type=type_,
        description=description,
        version=__version__,
        vendor_url="https://www.riken.jp/",
        port=port,
    )


def labware_tracker(
    plates: PlateTransferConfig, fluent: FluentBackendConfig, deck: DeckState | None = None
) -> LabwareTracker:
    """Where the labware moved by the RGA is (kept on the Fluent PC; in memory only in a dry run). With a deck state,
    the tracker is a view on it."""
    return LabwareTracker(plates, FluentPc(fluent.definitions), persist=not fluent.dry_run, deck=deck)


def deck_state(deck: DeckConfig, plates: PlateTransferConfig, backend: FluentControlBackend) -> DeckState | None:
    """The deck state, registered by the backend at the start of every run (None without deck.state_file). It takes
    over the positions of plates.positions_file once."""
    if not deck.state_file:
        return None
    fluent = backend.config
    state = DeckState(
        deck,
        fluent.definitions.workspace,
        FluentPc(fluent.definitions),
        persist=not fluent.dry_run,
        definitions=backend.preflight.definition_view,
        recorder=backend.write_record,
        legacy_file=plates.positions_file,
        legacy_labware=plates.labware,
    )
    backend.attach_deck(state)
    return state


def hands_off(deck: DeckConfig, backend: FluentControlBackend) -> HandsOff:
    """Hands-off of this server, also checked by the backend before every operation."""
    guard = HandsOff(backend, deck.hands_off_max_minutes)
    backend.hands_off = guard
    return guard


def deck_cameras(cameras: DeckCameraConfig, backend: FluentControlBackend) -> DeckCameras:
    """The deck cameras, also used by the backend for the images at StartRun and EndRun."""
    fluent = backend.config
    cams = DeckCameras(
        cameras, fluent.definitions.ssh_target, fluent.definitions.remote_dir + "\\records", fluent.dry_run
    )
    backend.cameras = cams
    cams.session_dir = lambda: backend.session_dir
    return cams
