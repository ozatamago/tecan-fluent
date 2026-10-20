"""Server assembly for the Inheco Incubator Shaker DWP on the Fluent 780 (through FluentControl).

uv run connector start --app unitelabs.tecan_fluent.apps.inheco_incubator:create_app -cfg config/inheco_incubator.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.fluent.status import Status
from ..features.inheco_incubator.shaking_incubator import ShakingIncubator
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from .common import sila_server

UUID = "e7757812-08c0-4d25-87e2-b54ab43ab316"


@dataclasses.dataclass
class InhecoIncubatorConnectorConfig(ConnectorBaseConfig):
    """Configuration for the Inheco shaking incubator connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "Inheco Shaking Incubator",
            "Incubator",
            "The Inheco Incubator Shaker DWP on the RIKEN BDR Tecan Fluent 780, driven through FluentControl: "
            "temperature, drawer and shaking.",
            UUID,
            50065,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)


def build_features(config: InhecoIncubatorConnectorConfig) -> list[sila.Feature]:
    """Build the Features of the Inheco shaking incubator, sharing one backend."""
    backend = FluentControlBackend(config.fluent)
    return [ShakingIncubator(backend), Status(backend)]


async def create_app(config: InhecoIncubatorConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
