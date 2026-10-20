"""A single SiLA 2 server, "Tecan Fluent 780", that combines the devices of the Fluent 780.

    uv run connector start --app unitelabs.tecan_fluent:create_app -cfg config.fluent780.json

Only one backend that sends commands to FluentControl (FluentOdtcBackend) is created and passed to every Feature.
The backend allows only one operation at a time, so ODTC and Infinite operations queue up automatically, and one
server can no longer finish the channel of another server's run (2026-10-15, ODTC and Infinite servers merged).

Each feature's category names its device (tecan.fluent, inheco.odtc, tecan.infinite, ...) and its display name
starts with the device, so the UniteLabs App shows the device first. docs/feature_identifiers.md maps the old
identifiers to the new ones.
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from .. import __version__
from ..features.colormix_demo import ColorMix
from ..features.deck_camera import DeckCamera
from ..features.door_controller import Door
from ..features.infinite import Absorbance, PlateHandling, Tray
from ..features.labware_controller import Labware
from ..features.liquid_handling import LiquidHandling
from ..features.method_controller import Methods
from ..features.rga_controller import PlateTransfer
from ..features.run_controller import RunControl
from ..features.status_controller import Status
from ..features.temperature_controller import Temperatures
from ..features.temperature_devices import (
    BioShake,
    CoolingHeatingPlates,
    Incubator1,
    ShakingIncubator,
)
from ..io.deck_cameras import DeckCameraConfig, DeckCameras
from ..io.definitions import FluentPc
from ..io.fluent_backend import FluentBackendConfig, FluentOdtcBackend
from ..io.infinite.reader import FluentInfiniteReader, InfiniteConfig
from ..io.labware_tracker import LabwareTracker, PlateTransferConfig


@dataclasses.dataclass
class Fluent780ConnectorConfig(ConnectorBaseConfig):
    """Configuration for the combined Fluent 780 connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: SiLAServerConfig(
            name="Tecan Fluent 780",
            type="Workcell",
            description=(
                "Devices of the RIKEN BDR Tecan Fluent 780, driven through FluentControl: Inheco ODTC 96 (door, "
                "methods, temperatures), Tecan Infinite 200 PRO (tray, absorbance, plate handling), the RGA plate "
                "gripper (moving labware, lids, gripper fingers; FluentControl's own labware statements inside a "
                "held-open run), BioShake, Inheco incubator, CPLC positions and Incubator1 (temperatures, shaking, "
                "doors). Every command is checked against the FluentControl definitions it uses and recorded on the "
                "Fluent PC before it is sent."
            ),
            version=__version__,
            vendor_url="https://www.riken.jp/",
            port=50060,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)
    infinite: InfiniteConfig = dataclasses.field(default_factory=InfiniteConfig)
    plates: PlateTransferConfig = dataclasses.field(default_factory=PlateTransferConfig)
    cameras: DeckCameraConfig = dataclasses.field(default_factory=DeckCameraConfig)


def build_features(config: Fluent780ConnectorConfig) -> list[sila.Feature]:
    """Build the Features of all devices, sharing one backend."""
    backend = FluentOdtcBackend(config.fluent)
    reader = FluentInfiniteReader(backend, config.infinite)
    tracker = LabwareTracker(config.plates, FluentPc(config.fluent.definitions), persist=not config.fluent.dry_run)
    cameras = DeckCameras(
        config.cameras,
        config.fluent.definitions.ssh_target,
        config.fluent.definitions.remote_dir + "\\records",
        config.fluent.dry_run,
    )
    backend.cameras = cameras
    cameras.session_dir = lambda: backend.session_dir
    liquid = LiquidHandling(backend)
    return [
        # RGA
        PlateTransfer(backend, tracker),
        Labware(backend, tracker),
        liquid,
        # ODTC
        Door(backend),
        Methods(backend),
        Temperatures(backend),
        # Infinite 200 PRO
        Tray(reader),
        Absorbance(reader),
        PlateHandling(reader, tracker),
        # Devices with temperature control (used in 01-07)
        BioShake(backend),
        ShakingIncubator(backend),
        CoolingHeatingPlates(backend),
        Incubator1(backend),
        # Demo
        ColorMix(backend, reader, liquid),
        # Overall
        DeckCamera(cameras),
        RunControl(backend),
        Status(backend),
    ]


async def create_app(config: Fluent780ConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
