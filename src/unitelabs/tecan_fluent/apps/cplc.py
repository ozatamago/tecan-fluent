"""Server assembly for the three Inheco CPLC positions on the Fluent 780 (through FluentControl).

uv run connector start --app unitelabs.tecan_fluent.apps.cplc:create_app -cfg config/cplc.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.cplc.cooling_heating_plates import CoolingHeatingPlates
from ..features.fluent.status import Status
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from .common import sila_server

UUID = "8b1f3420-ea62-4d60-962d-673ad0a8213f"


@dataclasses.dataclass
class CplcConnectorConfig(ConnectorBaseConfig):
    """Configuration for the CPLC connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "Inheco CPLC (3 positions)",
            "HeaterCooler",
            "The three Inheco CPLC cooling and heating positions on the RIKEN BDR Tecan Fluent 780, driven "
            "through FluentControl.",
            UUID,
            50066,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)


def build_features(config: CplcConnectorConfig) -> list[sila.Feature]:
    """Build the Features of the CPLC, sharing one backend."""
    backend = FluentControlBackend(config.fluent)
    backend.lock_owner = config.sila_server.name
    return [CoolingHeatingPlates(backend), Status(backend)]


async def create_app(config: CplcConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
