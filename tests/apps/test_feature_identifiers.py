"""Every server assembly serves exactly the features of docs/device_naming_spec.md section 1 (and Deck and HandsOff of
docs/deck_state_spec.md), with those fully qualified identifiers and display names (docs/feature_identifiers.md).
Nothing is sent; the apps are only built."""

import asyncio
import importlib
import typing

import pytest

ORIGINATOR = "jp.riken.bdr"
FEATURES = {
    # identifier: (category, display name)
    "RunControl": ("tecan.fluent", "Fluent - Run (Start / End)"),
    "Status": ("tecan.fluent", "Fluent - Status"),
    "Deck": ("tecan.fluent", "Fluent - Deck"),
    "HandsOff": ("tecan.fluent", "Fluent - Hands Off"),
    "LiquidHandling": ("tecan.fluent.arm", "FCA Arm - Liquid Handling"),
    "PlateTransfer": ("tecan.fluent.gripper", "RGA Gripper - Move & Return Plate"),
    "Labware": ("tecan.fluent.gripper", "RGA Gripper - Labware, Lids & Fingers"),
    "DeckCamera": ("tecan.fluent.camera", "Deck Cameras"),
    "Door": ("inheco.odtc", "ODTC - Door"),
    "Methods": ("inheco.odtc", "ODTC - Temperature Programs"),
    "Temperatures": ("inheco.odtc", "ODTC - Temperatures"),
    "Tray": ("tecan.infinite", "Infinite - Tray"),
    "Absorbance": ("tecan.infinite", "Infinite - Absorbance"),
    "PlateHandling": ("tecan.infinite", "Infinite - Plate In / Out (RGA)"),
    "BioShake": ("qinstruments.bioshake", "BioShake - Shake & Heat"),
    "ShakingIncubator": ("inheco.incubator", "Inheco Incubator - Shake & Heat"),
    "CoolingHeatingPlates": ("inheco.cplc", "Cooling / Heating Plates (CPLC 1-3)"),
    "Incubator1": ("tecan.incubator", "Incubator1 - Temperature, Shaker & Door"),
    "ColorMix": ("demo", "Demo - Color Mix & Measure"),
}
CORE = {
    "org.silastandard/core/SiLAService/v1": "SiLA Service",
    "org.silastandard/core/ConnectionConfigurationService/v1": "Connection Configuration Service",
}
APPS = {
    "fluent780_all": set(FEATURES),
    "fluent780": {
        "RunControl",
        "Status",
        "LiquidHandling",
        "PlateTransfer",
        "Labware",
        "DeckCamera",
        "Deck",
        "HandsOff",
    },
    "odtc": {"Door", "Methods", "Temperatures", "Status"},
    "infinite": {"Tray", "Absorbance", "PlateHandling", "Status"},
    "infinite_usb": {"Tray", "Absorbance"},
    "bioshake": {"BioShake", "Status"},
    "inheco_incubator": {"ShakingIncubator", "Status"},
    "cplc": {"CoolingHeatingPlates", "Status"},
    "incubator1": {"Incubator1", "Status"},
    "colormix_demo": {"ColorMix", "RunControl", "Status", "Absorbance", "LiquidHandling", "DeckCamera"},
}


def served(app: str) -> dict[str, str]:
    """Fully qualified identifier -> display name of every feature the app registers (default config: dry run)."""
    module = importlib.import_module(f"unitelabs.tecan_fluent.apps.{app}")
    config = typing.get_type_hints(module.create_app)["config"]()

    async def build():
        gen = module.create_app(config)
        connector = await gen.__anext__()
        await gen.aclose()
        return connector._sila_server.features

    features = asyncio.run(build())
    return {str(fqi): f.display_name for fqi, f in features.items()}


@pytest.mark.parametrize("app", sorted(APPS))
def test_app_serves_the_features_of_the_table(app):
    expected = dict(CORE)
    for identifier in APPS[app]:
        category, name = FEATURES[identifier]
        expected[f"{ORIGINATOR}/{category}/{identifier}/v1"] = name
    assert served(app) == expected


def test_combined_app_has_every_device_feature_and_the_core_features():
    features = served("fluent780_all")
    assert len(features) == 19 + 2
    assert {fqi.split("/")[2] for fqi in features if fqi.startswith(ORIGINATOR)} == set(FEATURES)


@pytest.mark.parametrize("app", ["fluent780_all", "infinite_usb"])
def test_feature_definitions_follow_the_sila_schema(app):
    # e.g. a category may hold only lower-case letters and dots (no digits), or SiLA clients refuse the server
    from sila.framework.fdl.serializer import Serializer
    from sila2.framework.utils import parse_feature_definition

    module = importlib.import_module(f"unitelabs.tecan_fluent.apps.{app}")
    config = typing.get_type_hints(module.create_app)["config"]()

    async def build():
        gen = module.create_app(config)
        connector = await gen.__anext__()
        await gen.aclose()
        return list(connector._sila_server.features.values())

    for feature in asyncio.run(build()):
        parse_feature_definition(Serializer.serialize(feature.serialize))


def test_package_entry_point_is_the_combined_app():
    import unitelabs.tecan_fluent as package
    from unitelabs.tecan_fluent.apps import fluent780_all

    assert package.create_app is fluent780_all.create_app
    assert package.Fluent780AllConnectorConfig is fluent780_all.Fluent780AllConnectorConfig
