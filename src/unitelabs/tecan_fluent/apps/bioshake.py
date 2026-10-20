"""Server assembly for the BioShake Q1 on the Fluent 780 (through FluentControl).

uv run connector start --app unitelabs.tecan_fluent.apps.bioshake:create_app -cfg config/bioshake.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.bioshake.bioshake import BioShake
from ..features.fluent.status import Status
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from .common import sila_server

UUID = "855e8397-dd4f-4949-a4df-80f3097d08c0"


@dataclasses.dataclass
class BioShakeConnectorConfig(ConnectorBaseConfig):
    """Configuration for the BioShake connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "BioShake",
            "Shaker",
            "The BioShake Q1 on the RIKEN BDR Tecan Fluent 780, driven through FluentControl: temperature, "
            "plate clamp and shaking.",
            UUID,
            50064,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)


def build_features(config: BioShakeConnectorConfig) -> list[sila.Feature]:
    """Build the Features of the BioShake, sharing one backend."""
    backend = FluentControlBackend(config.fluent)
    return [BioShake(backend), Status(backend)]


async def create_app(config: BioShakeConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
