"""A single SiLA 2 server, "Tecan Fluent 780 (All devices)", that combines every device of the Fluent 780.

    uv run connector start --app unitelabs.tecan_fluent:create_app -cfg config.fluent780.json

This is the server the Fluent PC runs (task OFML_Fluent780Server). The other modules in apps/ serve one device each.

Only one backend that sends commands to FluentControl (FluentControlBackend) is created and passed to every Feature.
The backend allows only one operation at a time, so ODTC and Infinite operations queue up automatically, and one
server can no longer finish the channel of another server's run (2026-10-15, ODTC and Infinite servers merged).

Each feature's category names its device (tecan.fluent, inheco.odtc, tecan.infinite, ...) and its display name
starts with the device, so the UniteLabs App shows the device first. docs/feature_identifiers.md maps the old
identifiers to the new ones.
"""

import collections.abc
import dataclasses

from unitelabs.cdk import Connector, ConnectorBaseConfig, SiLAServerConfig, sila

from ..features.bioshake.bioshake import BioShake
from ..features.cplc.cooling_heating_plates import CoolingHeatingPlates
from ..features.demo.colormix import ColorMix
from ..features.fluent.arm.liquid_handling import LiquidHandling
from ..features.fluent.camera.deck_camera import DeckCamera
from ..features.fluent.deck import Deck
from ..features.fluent.gripper.labware import Labware
from ..features.fluent.gripper.plate_transfer import PlateTransfer
from ..features.fluent.hands_off import HandsOff
from ..features.fluent.lab_capabilities import CapabilitiesConfig, LabCapabilities
from ..features.fluent.run_control import RunControl
from ..features.fluent.status import Status
from ..features.incubator1.incubator1 import Incubator1
from ..features.infinite.absorbance import Absorbance
from ..features.infinite.plate_handling import PlateHandling
from ..features.infinite.tray import Tray
from ..features.inheco_incubator.shaking_incubator import ShakingIncubator
from ..features.odtc.door import Door
from ..features.odtc.methods import Methods
from ..features.odtc.temperatures import Temperatures
from ..io.fluent.camera.deck_cameras import DeckCameraConfig
from ..io.fluent.deck.state import DeckConfig
from ..io.fluent.gripper.labware_tracker import PlateTransferConfig
from ..io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from ..io.infinite.reader import FluentInfiniteReader, InfiniteConfig
from .common import deck_cameras, deck_state, hands_off, labware_tracker, sila_server

UUID = "7c3f1e9a-2b5d-4a8e-b6c4-0d1f2e3a4b50"


@dataclasses.dataclass
class Fluent780AllConnectorConfig(ConnectorBaseConfig):
    """Configuration for the combined Fluent 780 connector (all devices)."""

    sila_server: SiLAServerConfig = dataclasses.field(
        default_factory=lambda: sila_server(
            "Tecan Fluent 780 (All devices)",
            "Workcell",
            "All devices of the RIKEN BDR Tecan Fluent 780 in one server, driven through FluentControl: the Fluent "
            "(runs, FCA arm, RGA gripper, deck cameras), ODTC 96, Infinite 200 PRO, BioShake, Inheco incubator, CPLC "
            "positions and Incubator1. Every command is checked against the FluentControl definitions it uses and "
            "recorded on the Fluent PC before it is sent.",
            UUID,
            50060,
        )
    )
    fluent: FluentBackendConfig = dataclasses.field(default_factory=FluentBackendConfig)
    infinite: InfiniteConfig = dataclasses.field(default_factory=InfiniteConfig)
    plates: PlateTransferConfig = dataclasses.field(default_factory=PlateTransferConfig)
    cameras: DeckCameraConfig = dataclasses.field(default_factory=DeckCameraConfig)
    deck: DeckConfig = dataclasses.field(default_factory=DeckConfig)
    capabilities: CapabilitiesConfig = dataclasses.field(default_factory=CapabilitiesConfig)


def build_features(config: Fluent780AllConnectorConfig) -> list[sila.Feature]:
    """Build the Features of all devices, sharing one backend."""
    backend = FluentControlBackend(config.fluent)
    backend.lock_owner = config.sila_server.name
    reader = FluentInfiniteReader(backend, config.infinite)
    deck = deck_state(config.deck, config.plates, backend)
    tracker = labware_tracker(config.plates, config.fluent, deck)
    cameras = deck_cameras(config.cameras, backend)
    liquid = LiquidHandling(backend)
    features: list[sila.Feature] = [
        # RGA
        PlateTransfer(backend, tracker),
        Labware(backend, tracker),
        liquid,
        # ODTC
        Door(backend),
        Methods(backend),
        Temperatures(backend),
        # Infinite 200 PRO
        Tray(reader),
        Absorbance(reader),
        PlateHandling(reader, tracker),
        # Devices with temperature control (used in 01-07)
        BioShake(backend),
        ShakingIncubator(backend),
        CoolingHeatingPlates(backend),
        Incubator1(backend),
        # Demo
        ColorMix(backend, reader, liquid),
        # Overall
        DeckCamera(cameras),
        RunControl(backend),
        Status(backend),
        Deck(backend, deck),
        HandsOff(hands_off(config.deck, backend)),
    ]
    features.append(LabCapabilities(config.capabilities, backend, deck, list(features)))
    return features


async def create_app(config: Fluent780AllConnectorConfig) -> collections.abc.AsyncGenerator[Connector, None]:
    """Create the connector application."""

    app = Connector(config)
    for feature in build_features(config):
        app.register(feature)
    yield app
