"""Server assembly for the ColorMix demo, with the features it uses (through FluentControl).

uv run connector start --app unitelabs.tecan_fluent.apps.colormix_demo:create_app -cfg config/colormix_demo.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.demo.colormix import ColorMix
from ..features.fluent.arm.liquid_handling import LiquidHandling
from ..features.fluent.camera.deck_camera import DeckCamera
from ..features.fluent.run_control import RunControl
from ..features.fluent.status import Status
from ..features.infinite.absorbance import Absorbance
from ..io.fluent.camera.deck_cameras import DeckCameraConfig
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from ..io.infinite.reader import FluentInfiniteReader, InfiniteConfig
from .common import deck_cameras, sila_server

UUID = "737d7686-f67a-4450-815a-6173e0b13ff9"


@dataclasses.dataclass
class ColorMixDemoConnectorConfig(ConnectorBaseConfig):
    """Configuration for the ColorMix demo connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "ColorMix Demo",
            "Demo",
            "Hackathon demo on the RIKEN BDR Tecan Fluent 780: pipette coloured water into a plate and measure it in "
            "the Infinite 200 PRO in one command, with the run, pipetting, reader and camera features it uses.",
            UUID,
            50068,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)
    infinite: InfiniteConfig = dataclasses.field(default_factory=InfiniteConfig)
    cameras: DeckCameraConfig = dataclasses.field(default_factory=DeckCameraConfig)


def build_features(config: ColorMixDemoConnectorConfig) -> list[sila.Feature]:
    """Build the demo and the Features it uses, sharing one backend."""
    backend = FluentControlBackend(config.fluent)
    reader = FluentInfiniteReader(backend, config.infinite)
    cameras = deck_cameras(config.cameras, backend)
    liquid = LiquidHandling(backend)
    return [
        ColorMix(backend, reader, liquid),
        RunControl(backend),
        Status(backend),
        Absorbance(reader),
        liquid,
        DeckCamera(cameras),
    ]


async def create_app(config: ColorMixDemoConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
