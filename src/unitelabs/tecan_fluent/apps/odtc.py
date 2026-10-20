"""Server assembly for the Inheco ODTC 96 in the Fluent 780 (through FluentControl).

    uv run connector start --app unitelabs.tecan_fluent.apps.odtc:create_app -cfg config/odtc.json

Kept for completeness: the stand-alone ODTC server is the separate inheco-odtc repository (port 50061 there too, so
run only one of them).
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.fluent.status import Status
from ..features.odtc.door import Door
from ..features.odtc.methods import Methods
from ..features.odtc.temperatures import Temperatures
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from .common import sila_server

UUID = "6a1d7c2e-0d6f-4b8e-9a51-3f0c2b7d9e10"


@dataclasses.dataclass
class OdtcConnectorConfig(ConnectorBaseConfig):
    """Configuration for the ODTC connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "Inheco ODTC (Fluent 780)",
            "ThermalCycler",
            "Control the Inheco ODTC 96 thermal cycler integrated in the Tecan Fluent 780.",
            UUID,
            50061,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)


def build_features(config: OdtcConnectorConfig) -> list[sila.Feature]:
    """Build the Features of the ODTC, sharing one backend (one operation at a time)."""
    backend = FluentControlBackend(config.fluent)
    backend.lock_owner = config.sila_server.name
    return [Door(backend), Methods(backend), Temperatures(backend), Status(backend)]


async def create_app(config: OdtcConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
