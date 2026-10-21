"""Every example config in config/ loads with the config class of its app and keeps that app's fixed UUID and port;
UUIDs and ports are unique across the apps."""

import importlib
import json
import pathlib
import typing

import pytest

CONFIG = pathlib.Path(__file__).resolve().parents[2] / "config"
EXAMPLES = {
    "fluent780_all": ["fluent780_all.fluentpc.example.json", "config.fluent780.example.json"],
    "fluent780": ["fluent780.fluentpc.example.json"],
    "odtc": ["odtc.fluentpc.example.json", "config.example.json"],
    "infinite": ["infinite.fluentpc.example.json", "config.infinite.example.json"],
    "infinite_usb": ["config.infinite_usb.example.json"],
    "bioshake": ["bioshake.fluentpc.example.json"],
    "inheco_incubator": ["inheco_incubator.fluentpc.example.json"],
    "cplc": ["cplc.fluentpc.example.json"],
    "incubator1": ["incubator1.fluentpc.example.json"],
    "colormix_demo": ["colormix_demo.fluentpc.example.json"],
}
COMBINED_UUID = "7c3f1e9a-2b5d-4a8e-b6c4-0d1f2e3a4b50"


def config_class(app: str):
    module = importlib.import_module(f"unitelabs.tecan_fluent.apps.{app}")
    return typing.get_type_hints(module.create_app)["config"]


def test_every_example_belongs_to_an_app():
    listed = {name for names in EXAMPLES.values() for name in names}
    assert {p.name for p in CONFIG.glob("*.json")} == listed


@pytest.mark.parametrize(("app", "name"), [(app, name) for app, names in EXAMPLES.items() for name in names])
def test_example_loads_and_keeps_the_app_identity(app, name):
    cls = config_class(app)
    config = cls.validate(json.loads((CONFIG / name).read_text(encoding="utf-8")))  # rejects unknown keys
    default = cls().sila_server
    assert (config.sila_server.uuid, config.sila_server.port) == (default.uuid, default.port)
    assert config.sila_server.name == default.name


@pytest.mark.parametrize("app", [app for app in EXAMPLES if app != "infinite_usb"])
def test_fluent_pc_example_runs_on_the_fluent_pc(app):
    data = json.loads((CONFIG / f"{app}.fluentpc.example.json").read_text(encoding="utf-8"))
    assert data["sila_server"]["hostname"] == "10.5.1.156"
    fluent = data["fluent"]
    assert (fluent["host"], fluent["port"], fluent["ssh_target"], fluent["dry_run"]) == (
        "127.0.0.1",
        51822,
        "local",
        False,
    )
    assert fluent["definitions"]["ssh_target"] == "local"


def test_servers_on_the_fluent_pc_never_share_local_files():
    dirs = [
        json.loads((CONFIG / f"{app}.fluentpc.example.json").read_text(encoding="utf-8"))["fluent"]["definitions"][
            "local_dir"
        ]
        for app in EXAMPLES
        if app != "infinite_usb"
    ]
    assert len(set(dirs)) == len(dirs)


def test_servers_with_the_deck_feature_share_one_deck_state_on_the_fluent_pc():
    from unitelabs.tecan_fluent.io.fluent.deck.state import DECK_FILE

    for app in ("fluent780_all", "fluent780"):
        config = config_class(app).validate(
            json.loads((CONFIG / f"{app}.fluentpc.example.json").read_text(encoding="utf-8"))
        )
        assert config.deck.state_file == DECK_FILE and config.deck.hands_off_max_minutes == 30
    # without the setting (e.g. a configuration copied before the deck state existed) there is no deck state
    assert config_class("fluent780_all")().deck.state_file == ""


def test_uuids_and_ports_are_unique_and_fixed():
    servers = {app: config_class(app)().sila_server for app in EXAMPLES}
    assert len({s.uuid for s in servers.values()}) == len(servers)
    assert len({s.port for s in servers.values()}) == len(servers)
    # fixed: a second default config of an app has the same UUID (the CDK would otherwise make a new one each time)
    assert all(config_class(app)().sila_server.uuid == s.uuid for app, s in servers.items())
    assert (servers["fluent780_all"].uuid, servers["fluent780_all"].port) == (COMBINED_UUID, 50060)
    assert {app: s.port for app, s in servers.items() if app not in ("fluent780_all", "odtc", "infinite_usb")} == {
        "fluent780": 50062,
        "infinite": 50063,
        "bioshake": 50064,
        "inheco_incubator": 50065,
        "cplc": 50066,
        "incubator1": 50067,
        "colormix_demo": 50068,
    }
