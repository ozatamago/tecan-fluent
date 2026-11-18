"""BioShake temperature reading: the macro sent, the log parsing and the failures. No instrument access.

The log lines have the form read from the instrument's .ulf on 2026-11-18 (io/bioshake/temperature.py)."""

import asyncio
from types import SimpleNamespace

import pytest

from fakes import macro_obj
from unitelabs.tecan_fluent.features.bioshake.bioshake import BioShake
from unitelabs.tecan_fluent.features.device_macro import TemperatureReadingFailed
from unitelabs.tecan_fluent.io.bioshake import temperature as module
from unitelabs.tecan_fluent.io.bioshake.temperature import (
    get_temp_xml,
    log_lines,
    log_script,
    parse_reading,
    read_temperature,
)
from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError, FluentBackendConfig, FluentControlBackend
from unitelabs.tecan_fluent.io.fluentcontrol.statements import legacy_macro_xml

SINCE = "2026-11-18 16:40:50.000"
PEGASUS = "Tecan/Pegasus/Pegasus/General"
DRIVER = "Tecan/Drivers/BioShake"


def line(message, stamp="2026-11-18 16:40:50.712", channel=PEGASUS, severity="Normal"):
    return f"{stamp}\t{severity}\t{channel}\t{message}"


def out(data, port=3, length=15):
    return f"<note>Serial {port} at host .: <clear><color=navy;style=bold>OUT [{length}]<clear> {data} <debug>"


def into(data, port=3, length=11):
    return f"<note>Serial {port} at host .: <clear><color=green;style=bold>IN [{length}]<clear> {data}"


GET = out("getTempActual{0D}{0A}")
REPLY = into("36.993000{0D}{0A}")


def rows(*lines):
    return log_lines("\n".join(lines), SINCE)


def test_macro_has_empty_settings_and_the_form_of_the_other_bioshake_macros():
    xml = get_temp_xml()
    assert macro_obj(xml) == macro_obj(legacy_macro_xml("BioShake", "BioShake_GetTemp"))
    assert "<ExecutionSettings />" in xml and 'ModuleName="BioShake"' in xml
    assert xml.count('Name="BioShake_') == 1


def test_log_script_selects_the_port_and_refuses_odd_ports():
    script = log_script(SINCE, 3)
    assert "*Serial 3 at host*" in script and SINCE in script and "__" not in script
    for port in (0, 100, "3", True):
        with pytest.raises(BackendError):
            log_script(SINCE, port)


def test_log_lines_drops_older_malformed_and_duplicate_lines_keeping_same_millisecond_order():
    text = "\n".join(
        [
            line(GET),
            line(REPLY),  # same millisecond as the OUT line: must stay after it
            line(GET, stamp="2026-11-18 16:40:49.999"),
            "not a log line",
            line(REPLY),
        ]
    )
    assert [r[3] for r in log_lines(text, SINCE)] == [GET, REPLY]


def test_the_instrument_lines_give_the_temperature_in_celsius():
    result = parse_reading(rows(line('<Response status="OK" />', channel=DRIVER), line(GET), line(REPLY)))
    assert result["temperature_c"] == 36.993 and result["serial_port"] == 3
    assert result["log_timestamp"] == "2026-11-18 16:40:50.712" and "getTempActual" in result["source"]


def test_any_lengths_and_html_escaped_lines():
    escaped = into("37.5{0D}{0A}", length=7).replace("<", "&lt;").replace(">", "&gt;")
    assert parse_reading(rows(line(out("getTempActual{0D}{0A}", length=9)), line(escaped)))["temperature_c"] == 37.5


def test_no_reply_without_a_preceding_get_temp_actual_on_the_same_port():
    assert parse_reading(rows(line(REPLY))) is None  # IN without the request
    assert parse_reading(rows(line(GET))) is None  # request, no reply yet
    assert parse_reading(rows(line(out("getTempActual{0D}{0A}", port=4)), line(into("36.9{0D}{0A}", port=4)))) is None
    # another command on the port in between: its reply is not a temperature
    assert parse_reading(rows(line(GET), line(out("getShakeActualSpeed{0D}{0A}")), line(into("0{0D}{0A}")))) is None
    # the driver channel's own reply has no value
    assert parse_reading(rows(line('<Response status="OK" />', channel=DRIVER))) is None


def test_other_ports_polled_in_between_are_ignored():
    inheco_out = out("{0A}2{C7}T00RAT1b", port=4)
    inheco_in = into("{B2}275{B2}", port=4)
    result = parse_reading(rows(line(GET), line(inheco_out), line(inheco_in), line(REPLY)))
    assert result["temperature_c"] == 36.993


def test_the_first_pair_after_the_request_is_taken():
    later = into("37.100000{0D}{0A}")
    result = parse_reading(
        rows(line(GET), line(REPLY), line(GET, stamp="2026-11-18 16:40:51.000"), line(later, "2026-11-18 16:40:51.010"))
    )
    assert result["temperature_c"] == 36.993


def test_the_configured_port_is_used():
    lines = rows(line(out("getTempActual{0D}{0A}", port=5)), line(into("42.000000{0D}{0A}", port=5)))
    assert parse_reading(lines) is None
    assert parse_reading(lines, 5)["temperature_c"] == 42.0


def test_a_reply_that_is_not_a_number_or_implausible_is_an_error_not_a_value():
    with pytest.raises(BackendError, match="not a number"):
        parse_reading(rows(line(GET), line(into("ERROR{0D}{0A}"))))
    with pytest.raises(BackendError, match="implausible"):
        parse_reading(rows(line(GET), line(into("369.93{0D}{0A}"))))


def fake_backend(log_text, run_open=True, dry_run=False, port=3):
    sent, records, scripts = [], [], []

    def steps(commands, report, extra, post):
        sent.extend(commands)
        records.append(post())

    def run_ps(script, timeout):
        scripts.append(script)
        return log_text.encode("utf-8")

    backend = SimpleNamespace(
        config=SimpleNamespace(dry_run=dry_run, bioshake_serial_port=port),
        run_open=run_open,
        _pc_now=lambda: SINCE,
        preflight=SimpleNamespace(pc=SimpleNamespace(run_ps=run_ps)),
        _run_steps=steps,
    )
    return backend, sent, records, scripts


def test_dry_run_or_no_open_run_sends_nothing():
    backend, sent, _, _ = fake_backend("", dry_run=True)
    with pytest.raises(BackendError, match="dry-run"):
        read_temperature(backend, lambda _: None)
    backend, sent, _, _ = fake_backend("", run_open=False)
    with pytest.raises(BackendError, match="open run"):
        read_temperature(backend, lambda _: None)
    assert sent == []


def test_read_sends_one_get_temp_and_returns_the_fresh_reply():
    text = "\n".join(
        [
            line(GET, stamp="2026-11-18 16:40:40.000"),
            line(into("25.0{0D}{0A}"), stamp="2026-11-18 16:40:40.010"),  # before the request
            line('<Response status="OK" />', channel=DRIVER),
            line(GET),
            line(REPLY),
        ]
    )
    backend, sent, records, scripts = fake_backend(text)
    result = read_temperature(backend, lambda _: None)
    assert result["temperature_c"] == 36.993
    assert records[0]["bioshake_temperature"]["temperature_c"] == 36.993
    assert len(sent) == 1 and "BioShake_GetTemp" in sent[0][1]
    assert "*Serial 3 at host*" in scripts[0]


def test_no_reply_fails_with_the_log_lines(monkeypatch):
    monkeypatch.setattr(module, "LOG_WAIT_S", 0.0)
    backend, _, records, _ = fake_backend(line('<Response status="OK" />', channel=DRIVER))
    with pytest.raises(BackendError, match="No reply to getTempActual on serial port 3") as err:
        read_temperature(backend, lambda _: None)
    assert "Response status" in str(err.value) and records[0]["bioshake_driver_log"]


def test_implausible_reply_fails():
    backend, _, _, _ = fake_backend("\n".join([line(GET), line(into("999{0D}{0A}"))]))
    with pytest.raises(BackendError, match="implausible"):
        read_temperature(backend, lambda _: None)


def test_unreadable_log_fails():
    def steps(commands, report, extra, post):
        try:
            post()
        except Exception:  # noqa: BLE001, S110 - _run_steps records post errors without raising
            pass

    backend, _, _, _ = fake_backend("")
    backend._run_steps = steps
    backend.preflight.pc.run_ps = lambda *_: (_ for _ in ()).throw(OSError("ssh failed"))
    with pytest.raises(BackendError, match="could not be read"):
        read_temperature(backend, lambda _: None)


def test_default_config_port_is_the_bioshake_port():
    assert FluentBackendConfig().bioshake_serial_port == 3


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
