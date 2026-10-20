"""Server assembly for a stand-alone Infinite 200 PRO (USB, PyLabRobot).

    uv run connector start --app unitelabs.tecan_fluent.apps.infinite_usb:create_usb_app -cfg config.infinite_usb.json

The features are the same as in the Fluent 780 Infinite server (Tray / Absorbance).
PlateHandling (RGA transfers) is not included. create_app is the same as create_usb_app, so this module can be started
like the others.
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig

from ..features.infinite.absorbance import Absorbance
from ..features.infinite.tray import Tray
from ..io.infinite.plr_reader import PyLabRobotInfiniteReader, UsbInfiniteConfig
from .common import sila_server

UUID = "1f3e5d7c-9b2a-4e6f-8c1d-3a5b7c9e0f2d"


@dataclasses.dataclass
class InfiniteUsbConnectorConfig(ConnectorBaseConfig):
    """Configuration for a stand-alone Infinite 200 PRO connected over USB."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "Tecan Infinite 200 PRO (USB)",
            "PlateReader",
            "Control a stand-alone Tecan Infinite 200 PRO plate reader over USB (PyLabRobot backend).",
            UUID,
            50069,
        )
    )
    reader: UsbInfiniteConfig = dataclasses.field(default_factory=UsbInfiniteConfig)


async def create_usb_app(config: InfiniteUsbConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    reader = PyLabRobotInfiniteReader(config.reader)
    app.register(Tray(reader))
    app.register(Absorbance(reader))
    yield app
    await reader.stop()


create_app = create_usb_app
