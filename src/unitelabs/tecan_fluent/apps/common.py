"""Parts shared by the server assemblies. No config class here (the UniteLabs CDK allows one per process)."""

from unitelabs.cdk import SiLAServerConfig

from .. import __version__
from ..io.fluent.camera.deck_cameras import DeckCameraConfig, DeckCameras
from ..io.fluent.gripper.labware_tracker import LabwareTracker, PlateTransferConfig
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from ..io.fluentcontrol.definitions import FluentPc


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


def labware_tracker(plates: PlateTransferConfig, fluent: FluentBackendConfig) -> LabwareTracker:
    """Where the labware moved by the RGA is (kept on the Fluent PC; in memory only in a dry run)."""
    return LabwareTracker(plates, FluentPc(fluent.definitions), persist=not fluent.dry_run)


def deck_cameras(cameras: DeckCameraConfig, backend: FluentControlBackend) -> DeckCameras:
    """The deck cameras, also used by the backend for the images at StartRun and EndRun."""
    fluent = backend.config
    cams = DeckCameras(
        cameras, fluent.definitions.ssh_target, fluent.definitions.remote_dir + "\\records", fluent.dry_run
    )
    backend.cameras = cams
    cams.session_dir = lambda: backend.session_dir
    return cams
