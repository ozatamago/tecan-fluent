"""Hands-off: the shared lock held on behalf of another robot (hands_off.py). Works on the local disk only; nothing is
sent (dry runs)."""

import asyncio
import json

import pytest

from unitelabs.tecan_fluent.features.fluent.hands_off import HandsOff, HandsOffFailed
from unitelabs.tecan_fluent.features.fluent.status import Status
from unitelabs.tecan_fluent.io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from unitelabs.tecan_fluent.io.fluentcontrol.errors import BackendError
from unitelabs.tecan_fluent.io.fluentcontrol.hands_off import HandsOff as Guard


class Clock:
    def __init__(self):
        self.now = 1_792_000_000.0

    def __call__(self):
        return self.now


def _server(tmp_path, name, clock=None):
    backend = FluentControlBackend(FluentBackendConfig(shared_lock=str(tmp_path / "fluentcontrol.lock")))
    backend.lock_owner = name
    backend.hands_off = Guard(backend, 30, clock or Clock())
    return backend


def test_hands_off_is_refused_by_every_server_until_end(tmp_path):
    a, b = _server(tmp_path, "Server A"), _server(tmp_path, "Server B")
    feature = HandsOff(a.hands_off)

    async def scenario():
        token = await feature.begin("Franka", "puts a plate on Nest7mm_Pos[1]", 0)
        expected = r"hands-off by Franka \(puts a plate on Nest7mm_Pos\[1\], since 20"
        with pytest.raises(BackendError, match=expected):
            await b.run_macro("SiLA-ODTC_OpenDoor")  # another server
        with pytest.raises(BackendError, match=expected):
            await a.run_macro("SiLA-ODTC_OpenDoor")  # the holding server itself
        with pytest.raises(BackendError, match=expected):
            await a.start_run()
        assert (await feature.get_state()).startswith("hands-off by Franka") and "until" in await feature.get_state()
        assert (await HandsOff(b.hands_off).get_state()).startswith("hands-off by Franka")  # seen from the other one
        for backend, prefix in ((a, "hands-off by Franka"), (b, "another server: hands-off by Franka")):
            status = Status(backend)
            assert (await status.get_current_operation()).startswith(prefix)
            assert await status.get_ready() is False
        with pytest.raises(HandsOffFailed, match="Already hands-off by Franka"):
            await feature.begin("Kachaka", "brings a plate", 0)
        with pytest.raises(HandsOffFailed, match="in use by another server"):
            await HandsOff(b.hands_off).begin("Kachaka", "brings a plate", 0)
        with pytest.raises(HandsOffFailed, match="Wrong token"):
            await feature.end("0000")
        assert (await feature.end(token)).startswith("hands-off by Franka")
        assert await feature.get_state() == "" and await HandsOff(b.hands_off).get_state() == ""
        await b.run_macro("SiLA-ODTC_OpenDoor")
        await a.run_macro("SiLA-ODTC_CloseDoor")

    asyncio.run(scenario())
    records = sorted(
        p.name.split("_", 1)[1] for p in (tmp_path / ".riken_fluent780" / "dry-run" / "hands_off").iterdir()
    )
    assert records == ["begin.json", "end.json"]


def test_hands_off_is_released_after_max_minutes(tmp_path):
    clock = Clock()
    a, b = _server(tmp_path, "Server A", clock), _server(tmp_path, "Server B")
    a.hands_off.begin("Kachaka", "docking", 5)
    with pytest.raises(BackendError, match="hands-off by Kachaka"):
        asyncio.run(b.run_macro("SiLA-ODTC_OpenDoor"))
    clock.now += 4 * 60
    assert a.hands_off.text.startswith("hands-off by Kachaka")
    clock.now += 61  # 5 minutes and 1 second
    assert a.hands_off.expire_if_due() and a.hands_off.text == "" and not a.shared.held
    asyncio.run(b.run_macro("SiLA-ODTC_OpenDoor"))
    folder = tmp_path / ".riken_fluent780" / "dry-run" / "hands_off"
    [expired] = [p for p in folder.iterdir() if p.name.endswith("_expired.json")]
    data = json.loads(expired.read_text())
    assert data["who"] == "Kachaka" and data["max_minutes"] == 5


def test_max_minutes_is_bounded_by_the_setting(tmp_path):
    a = _server(tmp_path, "Server A")
    with pytest.raises(BackendError, match="MaxMinutes is at most 30"):
        a.hands_off.begin("Franka", "too long", 45)
    with pytest.raises(BackendError, match="Who must not be empty"):
        a.hands_off.begin(" ", "nobody", 5)


def test_hands_off_is_refused_while_a_run_is_open_or_a_command_is_sent(tmp_path):
    a, b = _server(tmp_path, "Server A"), _server(tmp_path, "Server B")

    async def scenario():
        await a.start_run()
        with pytest.raises(BackendError, match="A run is open"):
            a.hands_off.begin("Franka", "loading", 0)
        with pytest.raises(BackendError, match="in use by another server.*Server A: Run: StartRun"):
            b.hands_off.begin("Franka", "loading", 0)
        await a.end_run()
        a.config.dry_run_seconds = 0.5
        sending = asyncio.create_task(a.run_macro("SiLA-ODTC_OpenDoor"))
        await asyncio.sleep(0.1)
        with pytest.raises(BackendError, match="Another operation is running"):
            a.hands_off.begin("Franka", "loading", 0)
        await sending
        a.hands_off.begin("Franka", "loading", 0)

    asyncio.run(scenario())


def test_without_a_shared_lock_only_this_server_refuses(tmp_path):
    backend = FluentControlBackend(FluentBackendConfig())
    backend.hands_off = Guard(backend, 30, Clock())
    token = backend.hands_off.begin("a person", "cleaning", 0)
    with pytest.raises(BackendError, match="hands-off by a person"):
        asyncio.run(backend.run_macro("SiLA-ODTC_OpenDoor"))
    backend.hands_off.end(token)
    asyncio.run(backend.run_macro("SiLA-ODTC_OpenDoor"))
