"""Server assembly for the Infinite 200 PRO in the Fluent 780 (through FluentControl).

    uv run connector start --app unitelabs.tecan_fluent.apps.infinite_fluent:create_app -cfg config.infinite.json
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig

from .. import __version__
from ..io.fluent_backend import FluentBackendConfig, FluentOdtcBackend
from ..features.infinite import AbsorbanceReader, FluentPlateHandling, TrayController
from ..io.infinite.reader import FluentInfiniteReader, InfiniteConfig



@dataclasses.dataclass
class InfiniteConnectorConfig(ConnectorBaseConfig):
    """Configuration for the Infinite 200 PRO connector."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: SiLAServerConfig(
            name="Tecan Infinite 200 PRO (Fluent 780)",
            type="PlateReader",
            description="Control the Tecan Infinite 200 PRO plate reader integrated in the Tecan Fluent 780.",
            version=__version__,
            vendor_url="https://www.riken.jp/",
            port=50063,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)
    infinite: InfiniteConfig = dataclasses.field(default_factory=InfiniteConfig)


async def create_app(config: InfiniteConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    reader = FluentInfiniteReader(FluentOdtcBackend(config.fluent), config.infinite)
    app.register(TrayController(reader))
    app.register(AbsorbanceReader(reader))
    app.register(FluentPlateHandling(reader))
    yield app
