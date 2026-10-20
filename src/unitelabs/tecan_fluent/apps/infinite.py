"""Server assembly for the Infinite 200 PRO in the Fluent 780 (through FluentControl).

uv run connector start --app unitelabs.tecan_fluent.apps.infinite:create_app -cfg config/infinite.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.fluent.status import Status
from ..features.infinite.absorbance import Absorbance
from ..features.infinite.plate_handling import PlateHandling
from ..features.infinite.tray import Tray
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from ..io.infinite.reader import FluentInfiniteReader, InfiniteConfig
from .common import sila_server

UUID = "371acb9a-2c10-4e34-9b05-ee7061522fc9"


@dataclasses.dataclass
class InfiniteConnectorConfig(ConnectorBaseConfig):
    """Configuration for the Infinite 200 PRO connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "Tecan Infinite 200 PRO",
            "PlateReader",
            "The Tecan Infinite 200 PRO plate reader integrated in the RIKEN BDR Tecan Fluent 780, driven through "
            "FluentControl: tray, absorbance, and plates brought in and out by the RGA gripper.",
            UUID,
            50063,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)
    infinite: InfiniteConfig = dataclasses.field(default_factory=InfiniteConfig)


def build_features(config: InfiniteConnectorConfig) -> list[sila.Feature]:
    """Build the Features of the reader, sharing one backend."""
    backend = FluentControlBackend(config.fluent)
    reader = FluentInfiniteReader(backend, config.infinite)
    return [Tray(reader), Absorbance(reader), PlateHandling(reader), Status(backend)]


async def create_app(config: InfiniteConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
