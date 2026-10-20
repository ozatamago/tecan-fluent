"""Server assembly for Incubator1 (6 Nest Incubator Shaking) on the Fluent 780 (through FluentControl).

uv run connector start --app unitelabs.tecan_fluent.apps.incubator1:create_app -cfg config/incubator1.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.fluent.status import Status
from ..features.incubator1.incubator1 import Incubator1
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from .common import sila_server

UUID = "23181691-39e9-4385-9cd7-60399e2d0310"


@dataclasses.dataclass
class Incubator1ConnectorConfig(ConnectorBaseConfig):
    """Configuration for the Incubator1 connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "Incubator1 (6 positions)",
            "Incubator",
            "Incubator1 (6 Nest Incubator Shaking) on the RIKEN BDR Tecan Fluent 780, driven through "
            "FluentControl: temperature, shaker and door.",
            UUID,
            50067,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)


def build_features(config: Incubator1ConnectorConfig) -> list[sila.Feature]:
    """Build the Features of the Incubator1, sharing one backend."""
    backend = FluentControlBackend(config.fluent)
    return [Incubator1(backend), Status(backend)]


async def create_app(config: Incubator1ConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
