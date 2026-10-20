"""Assembly of the ODTC connector server (config and create_app).

    uv run connector start --app unitelabs.tecan_fluent.apps.odtc:create_app -cfg config.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig

from .. import __version__
from ..features.door_controller import DoorController
from ..io.fluent_backend import FluentBackendConfig, FluentOdtcBackend
from ..features.method_controller import MethodController
from ..features.status_controller import StatusController
from ..features.temperature_controller import TemperatureController



@dataclasses.dataclass
class OdtcConnectorConfig(ConnectorBaseConfig):
    """Configuration for the ODTC connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: SiLAServerConfig(
            name="Inheco ODTC (Fluent 780)",
            type="ThermalCycler",
            description="Control the Inheco ODTC 96 thermal cycler integrated in the Tecan Fluent 780.",
            version=__version__,
            vendor_url="https://www.riken.jp/",
            port=50061,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)


async def create_app(config: OdtcConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    backend = FluentOdtcBackend(config.fluent)  # door and method share one backend, one operation at a time
    app.register(DoorController(backend))
    app.register(MethodController(backend))
    app.register(TemperatureController(backend))
    app.register(StatusController(backend))
    yield app
