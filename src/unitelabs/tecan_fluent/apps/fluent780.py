"""Server assembly for the Tecan Fluent 780 itself (runs, FCA arm, RGA gripper, deck cameras), through FluentControl.

uv run connector start --app unitelabs.tecan_fluent.apps.fluent780:create_app -cfg config/fluent780.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.fluent.arm.liquid_handling import LiquidHandling
from ..features.fluent.camera.deck_camera import DeckCamera
from ..features.fluent.gripper.labware import Labware
from ..features.fluent.gripper.plate_transfer import PlateTransfer
from ..features.fluent.run_control import RunControl
from ..features.fluent.status import Status
from ..io.fluent.camera.deck_cameras import DeckCameraConfig
from ..io.fluent.gripper.labware_tracker import PlateTransferConfig
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from .common import deck_cameras, labware_tracker, sila_server

UUID = "17ad5c72-0927-4823-945c-8e8fe70e3f6a"


@dataclasses.dataclass
class Fluent780ConnectorConfig(ConnectorBaseConfig):
    """Configuration for the Fluent 780 connector (the Fluent itself, without the integrated devices)."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "Tecan Fluent 780",
            "LiquidHandler",
            "The RIKEN BDR Tecan Fluent 780 itself, driven through FluentControl: runs shared by several commands, "
            "pipetting with the Air FCA arm, labware moves with the RGA gripper, and the deck cameras.",
            UUID,
            50062,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)
    plates: PlateTransferConfig = dataclasses.field(default_factory=PlateTransferConfig)
    cameras: DeckCameraConfig = dataclasses.field(default_factory=DeckCameraConfig)


def build_features(config: Fluent780ConnectorConfig) -> list[sila.Feature]:
    """Build the Features of the Fluent, sharing one backend."""
    backend = FluentControlBackend(config.fluent)
    backend.lock_owner = config.sila_server.name
    tracker = labware_tracker(config.plates, config.fluent)
    cameras = deck_cameras(config.cameras, backend)
    return [
        RunControl(backend),
        Status(backend),
        LiquidHandling(backend),
        PlateTransfer(backend, tracker),
        Labware(backend, tracker),
        DeckCamera(cameras),
    ]


async def create_app(config: Fluent780ConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
