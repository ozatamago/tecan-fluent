"""The lock that lets only one server on the Fluent PC use FluentControl at a time. Works on the local disk only."""

import asyncio

import pytest

from unitelabs.tecan_fluent.io.fluentcontrol.backend import FluentBackendConfig, FluentControlBackend
from unitelabs.tecan_fluent.io.fluentcontrol.errors import BackendError
from unitelabs.tecan_fluent.io.fluentcontrol.shared_lock import SharedLock


def test_second_holder_is_refused_and_told_who_holds_it(tmp_path):
    path = str(tmp_path / "fluentcontrol.lock")
    a, b = SharedLock(path, "Server A"), SharedLock(path, "Server B")
    a.acquire("ODTC: SiLA-ODTC_OpenDoor")
    with pytest.raises(BackendError, match="Server A: ODTC: SiLA-ODTC_OpenDoor"):
        b.acquire("BioShake: on")
    assert b.other_holder().startswith("Server A") and a.other_holder() == ""
    a.release()
    assert b.other_holder() == ""
    b.acquire("BioShake: on")
    assert b.held
    b.release()


def _backend(tmp_path, name):
    cfg = FluentBackendConfig(shared_lock=str(tmp_path / "fluentcontrol.lock"))  # dry_run by default
    backend = FluentControlBackend(cfg)
    backend.lock_owner = name
    return backend


def test_two_servers_do_not_send_at_the_same_time(tmp_path):
    a, b = _backend(tmp_path, "Server A"), _backend(tmp_path, "Server B")

    async def scenario():
        a.config.dry_run_seconds = 0.5
        first = asyncio.create_task(a.run_macro("SiLA-ODTC_OpenDoor"))
        await asyncio.sleep(0.1)
        assert b.other_server().startswith("Server A")
        with pytest.raises(BackendError, match="in use by another server"):
            await b.run_macro("SiLA-ODTC_CloseDoor")
        await first
        assert b.other_server() == ""
        await b.run_macro("SiLA-ODTC_CloseDoor")

    asyncio.run(scenario())


def test_a_run_held_open_keeps_the_lock_until_end_run(tmp_path):
    a, b = _backend(tmp_path, "Server A"), _backend(tmp_path, "Server B")

    async def scenario():
        await a.start_run()
        with pytest.raises(BackendError, match="Server A: Run: StartRun"):
            await b.run_macro("SiLA-ODTC_OpenDoor")
        await a.run_macro("SiLA-ODTC_OpenDoor")  # the holder itself goes on
        assert a.shared.held
        await a.end_run()
        assert not a.shared.held
        await b.run_macro("SiLA-ODTC_OpenDoor")

    asyncio.run(scenario())


def test_no_lock_configured_changes_nothing(tmp_path):
    backend = FluentControlBackend(FluentBackendConfig())
    assert backend.shared is None and backend.other_server() == ""
    asyncio.run(backend.run_macro("SiLA-ODTC_OpenDoor"))
