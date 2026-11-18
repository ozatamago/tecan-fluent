"""BioShake temperature reading: the macro sent, the log parsing and the failures. No instrument access.

The log format of BioShake_GetTemp is not confirmed yet (io/bioshake/temperature.py), so the parsing is tested with
a synthetic pattern and log lines."""

import asyncio
import re
from types import SimpleNamespace

import pytest

from fakes import macro_obj
from unitelabs.tecan_fluent.features.bioshake.bioshake import BioShake
from unitelabs.tecan_fluent.features.device_macro import TemperatureReadingFailed
from unitelabs.tecan_fluent.io.bioshake import temperature as module
from unitelabs.tecan_fluent.io.bioshake.temperature import get_temp_xml, log_lines, parse_reading, read_temperature
from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError, FluentBackendConfig, FluentControlBackend
from unitelabs.tecan_fluent.io.fluentcontrol.statements import legacy_macro_xml

SINCE = "2026-11-18 14:00:00.000"
PATTERN = re.compile(r"BioShake.*GetTemp.*?: (?P<value>-?\d+(?:\.\d+)?)\s*$")
CHANNEL = "Tecan/VisionX/Legacy Driver/BioShake"


def line(message, stamp="2026-11-18 14:00:01.000", channel=CHANNEL, severity="Info"):
    return f"{stamp}\t{severity}\t{channel}\t{message}"


def test_macro_reads_only_and_has_the_form_of_the_other_bioshake_macros():
    xml = get_temp_xml()
    assert macro_obj(xml) == macro_obj(legacy_macro_xml("BioShake", "BioShake_GetTemp"))
    assert 'Name="BioShake_GetTemp"' in xml and 'ModuleName="BioShake"' in xml
    assert xml.count('Name="BioShake_') == 1


def test_log_lines_drops_older_and_malformed_lines_and_sorts():
    text = "\n".join(
        [
            line("late", stamp="2026-11-18 14:00:03.000"),
            line("old", stamp="2026-11-18 13:59:59.999"),
            "not a log line",
            line("early", stamp="2026-11-18 14:00:02.000"),
        ]
    )
    assert [r[3] for r in log_lines(text, SINCE)] == ["early", "late"]


def test_unknown_format_never_yields_a_value():
    rows = log_lines(line("BioShake GetTemp returned: 42.0"), SINCE)
    assert module.TEMPERATURE_LINE is None  # still unconfirmed: change this test together with the constant
    assert parse_reading(rows) is None


def test_parse_with_a_known_pattern_and_scale():
    rows = log_lines(
        "\n".join(
            [line("BioShake SetTemp 42"), line("BioShake GetTemp returned: 418", stamp="2026-11-18 14:00:02.000")]
        ),
        SINCE,
    )
    result = parse_reading(rows, PATTERN, 0.1)
    assert result["temperature_c"] == 41.8 and result["log_timestamp"] == "2026-11-18 14:00:02.000"
    assert result["source"].startswith("BioShake_GetTemp")
    with pytest.raises(BackendError, match="implausible"):
        parse_reading(rows, PATTERN, 1.0)  # 418 degC


def test_a_pattern_without_a_value_group_is_an_error_not_a_value():
    rows = log_lines(line("BioShake GetTemp returned: 42"), SINCE)
    with pytest.raises(BackendError, match="not a number"):
        parse_reading(rows, re.compile(r"GetTemp"), 1.0)


def fake_backend(log_text, run_open=True, dry_run=False):
    sent = []
    records = []

    def steps(commands, report, extra, post):
        sent.extend(commands)
        records.append(post())

    pc = SimpleNamespace(run_ps=lambda script, timeout: log_text.encode("utf-8"))
    backend = SimpleNamespace(
        config=SimpleNamespace(dry_run=dry_run),
        run_open=run_open,
        _pc_now=lambda: SINCE,
        preflight=SimpleNamespace(pc=pc),
        _run_steps=steps,
    )
    return backend, sent, records


def test_dry_run_or_no_open_run_sends_nothing():
    backend, sent, _ = fake_backend("", dry_run=True)
    with pytest.raises(BackendError, match="dry-run"):
        read_temperature(backend, lambda _: None)
    backend, sent, _ = fake_backend("", run_open=False)
    with pytest.raises(BackendError, match="open run"):
        read_temperature(backend, lambda _: None)
    assert sent == []


def test_unconfirmed_format_fails_with_the_driver_log_lines(monkeypatch):
    monkeypatch.setattr(module, "LOG_WAIT_S", 0.0)
    backend, sent, records = fake_backend(line("BioShake GetTemp returned: 42.0"))
    with pytest.raises(BackendError, match="not known yet") as err:
        read_temperature(backend, lambda _: None)
    assert "GetTemp returned: 42.0" in str(err.value)
    assert len(sent) == 1 and "BioShake_GetTemp" in sent[0][1]
    assert records[0]["bioshake_driver_log"]


def test_confirmed_format_returns_the_fresh_value(monkeypatch):
    monkeypatch.setattr(module, "TEMPERATURE_LINE", PATTERN)
    monkeypatch.setattr(module, "VALUE_SCALE", 1.0)
    text = "\n".join(
        [
            line("BioShake GetTemp returned: 25.0", stamp="2026-11-18 13:59:00.000"),
            line("BioShake GetTemp returned: 37.2"),
        ]
    )
    backend, sent, records = fake_backend(text)
    result = read_temperature(backend, lambda _: None)
    assert result["temperature_c"] == 37.2
    assert records[0]["bioshake_temperature"]["temperature_c"] == 37.2 and len(sent) == 1


def test_confirmed_format_but_no_reply_fails(monkeypatch):
    monkeypatch.setattr(module, "TEMPERATURE_LINE", PATTERN)
    monkeypatch.setattr(module, "LOG_WAIT_S", 0.0)
    backend, _, _ = fake_backend(line("BioShake GetTemp returned: 25.0", stamp="2026-11-18 13:59:00.000"))
    with pytest.raises(BackendError, match="No BioShake temperature"):
        read_temperature(backend, lambda _: None)


def test_implausible_value_fails(monkeypatch):
    monkeypatch.setattr(module, "TEMPERATURE_LINE", PATTERN)
    backend, _, _ = fake_backend(line("BioShake GetTemp returned: 999"))
    with pytest.raises(BackendError, match="implausible"):
        read_temperature(backend, lambda _: None)


def test_unreadable_log_fails(monkeypatch):
    def steps(commands, report, extra, post):
        try:
            post()
        except Exception:  # noqa: BLE001 - _run_steps records post errors without raising
            pass

    backend, _, _ = fake_backend("")
    backend._run_steps = steps
    backend.preflight.pc.run_ps = lambda *_: (_ for _ in ()).throw(OSError("ssh failed"))
    with pytest.raises(BackendError, match="could not be read"):
        read_temperature(backend, lambda _: None)


def test_backend_uses_the_shared_lock(monkeypatch):
    backend = FluentControlBackend(FluentBackendConfig())

    def fake_read(b, report):
        assert b is backend and b.busy
        return {"temperature_c": 42.0, "log_timestamp": SINCE, "source": "test"}

    monkeypatch.setattr(module, "read_temperature", fake_read)
    assert asyncio.run(backend.read_bioshake_temperature())["temperature_c"] == 42.0
    assert not backend.busy


def test_feature_returns_the_reading_or_an_error():
    status = SimpleNamespace(update=lambda **_: None)

    async def ok():
        return {"temperature_c": 42.0, "log_timestamp": SINCE, "source": "test"}

    reading = asyncio.run(BioShake(SimpleNamespace(read_bioshake_temperature=ok)).read_temperature(status=status))
    assert reading.temperature_c == 42.0 and reading.log_timestamp == SINCE

    async def fail():
        raise BackendError("no open run")

    with pytest.raises(TemperatureReadingFailed, match="no open run"):
        asyncio.run(BioShake(SimpleNamespace(read_bioshake_temperature=fail)).read_temperature(status=status))
