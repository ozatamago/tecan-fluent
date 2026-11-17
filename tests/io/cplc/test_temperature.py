"""Read-only CPLC behavior, log provenance and missing-macro failures. No instrument access."""

import asyncio
import html
from types import SimpleNamespace

import pytest

from unitelabs.tecan_fluent.features.cplc.cooling_heating_plates import (
    CoolingHeatingPlates,
    TemperatureReadingFailed,
)
from unitelabs.tecan_fluent.io.cplc.macros import mtc_read_temperature_xml
from unitelabs.tecan_fluent.io.cplc.temperature import check_read_macro, parse_reading, read_temperature
from unitelabs.tecan_fluent.io.fluentcontrol.backend import BackendError, FluentBackendConfig, FluentControlBackend

SINCE = "2026-11-17 14:00:00.000"
INI = """// driver configuration
[Assembly]
Interface=Tecan.inhecoMTC
[Settings]
Slot1=True
Slot2=True
Slot3=True
[Macros]
macro1=inhecoMTC_SetTemperature
macro2=inhecoMTC_StartShake
macro3=inhecoMTC_StopShake
macro4=inhecoMTC_Shake
macro5=inhecoMTC_GetTemperature
:0012345
"""


def record(slot=1, value="245", timestamp="2026-11-17 14:00:00.100"):
    return {
        "timestamp": timestamp,
        "message": f"SlotId: {slot} Int32 Device.GetTemperature(Int32 pSlot=value[i],DateTime pFinishByTime=value[i]): {value}",
    }


@pytest.mark.parametrize("slot", [1, 2, 3])
def test_xml_contains_only_the_read_macro_with_no_output_variable(slot):
    xml = mtc_read_temperature_xml(slot)
    assert 'Name="inhecoMTC_GetTemperature"' in xml and f">{slot},,0<" in xml
    assert not any(x in xml for x in ["SetTemperature", "StartShake", "StopShake", "RoMa", "RGA", "Enable"])


@pytest.mark.parametrize("slot", [0, 4, True, 1.0, "1"])
def test_invalid_slot_cannot_form_a_driver_command(slot):
    with pytest.raises(ValueError):
        mtc_read_temperature_xml(slot)


def test_active_ini_requires_the_known_id_mapping_and_enabled_slot():
    assert len(check_read_macro(INI, 1)) == 64
    with pytest.raises(BackendError, match="not enabled"):
        check_read_macro(INI.replace("macro5=inhecoMTC_GetTemperature\n", ""), 1)
    with pytest.raises(BackendError, match="not enabled"):
        check_read_macro(INI.replace("macro5=", "macro6="), 1)
    with pytest.raises(BackendError, match="disabled"):
        check_read_macro(INI.replace("Slot1=True", "Slot1=False"), 1)


def test_parse_units_slot_and_freshness():
    rows = [record(timestamp="2026-11-17 13:59:59.999"), record(slot=2, value="999"), record()]
    result = parse_reading(rows, 1, SINCE)
    assert result["temperature_c"] == 24.5 and result["raw_tenths_c"] == 245
    assert result["slot"] == 1 and result["log_timestamp"].endswith("00.100")
    assert parse_reading(rows[:2], 1, SINCE) is None
    assert parse_reading([record(value="NaN")], 1, SINCE) is None
    assert parse_reading([record(value="24.5")], 1, SINCE) is None
    assert parse_reading([record(value="-35")], 1, SINCE)["temperature_c"] == -3.5


def test_entry_and_other_temperature_sources_are_not_measurements():
    rows = [record(value="Entered"), record()]
    rows[1]["message"] = rows[1]["message"].replace("Device.GetTemperature", "Device.SetTemperature")
    assert parse_reading(rows, 1, SINCE) is None


def test_unreasonable_or_unparseable_reply_never_becomes_a_value():
    with pytest.raises(BackendError, match="plausibility"):
        parse_reading([record(value="99999")], 1, SINCE)
    row = record()
    row["message"] = html.escape(html.escape(row["message"]))
    assert parse_reading([row], 1, SINCE)["temperature_c"] == 24.5


def test_dry_run_or_missing_run_does_not_send_a_macro():
    backend = SimpleNamespace(config=SimpleNamespace(dry_run=True), run_open=False)
    with pytest.raises(BackendError, match="dry-run"):
        read_temperature(backend, 1, lambda _: None)
    backend.config.dry_run = False
    with pytest.raises(BackendError, match="already open"):
        read_temperature(backend, 1, lambda _: None)


def test_missing_macro_fails_before_running_steps(monkeypatch):
    from unitelabs.tecan_fluent.io.cplc import temperature as module

    monkeypatch.setattr(module, "_ps", lambda *_: INI.replace("macro5=inhecoMTC_GetTemperature\n", ""))
    backend = SimpleNamespace(config=SimpleNamespace(dry_run=False, cplc_driver_ini="driver.ini"), run_open=True)
    with pytest.raises(BackendError, match="not enabled"):
        read_temperature(backend, 1, lambda _: None)


def test_success_sends_one_read_and_records_the_actual_value(monkeypatch):
    from unitelabs.tecan_fluent.io.cplc import temperature as module

    replies = iter([INI, SINCE, __import__("json").dumps([record()])])
    monkeypatch.setattr(module, "_ps", lambda *_: next(replies))
    sent = []

    def steps(commands, report, extra, post):
        sent.extend(commands)
        assert extra["read_only_device_command"]
        assert post()["cplc_temperature"]["temperature_c"] == 24.5

    backend = SimpleNamespace(
        config=SimpleNamespace(dry_run=False, cplc_driver_ini="driver.ini"), run_open=True, _run_steps=steps
    )
    assert read_temperature(backend, 1, lambda _: None)["temperature_c"] == 24.5
    assert len(sent) == 1 and "inhecoMTC_GetTemperature" in sent[0][1]


def test_backend_uses_the_shared_lock_and_leaves_run_untouched(monkeypatch):
    from unitelabs.tecan_fluent.io.cplc import temperature as module

    backend = FluentControlBackend(FluentBackendConfig())
    backend._session = {"rel": "existing", "started": "original", "commands": 0}
    original = backend._session.copy()

    def fake_read(b, slot, report):
        assert b is backend and b.busy
        return {"slot": slot, "temperature_c": 24.5, "log_timestamp": SINCE, "source": "test"}

    monkeypatch.setattr(module, "read_temperature", fake_read)
    assert asyncio.run(backend.read_cplc_temperature(1))["temperature_c"] == 24.5
    assert backend._session == original and not backend.busy


def test_feature_exposes_errors_instead_of_a_dummy_temperature():
    async def fail(*_):
        raise BackendError("missing read macro")

    feature = CoolingHeatingPlates(SimpleNamespace(read_cplc_temperature=fail))
    status = SimpleNamespace(update=lambda **_: None)
    with pytest.raises(TemperatureReadingFailed, match="missing read macro"):
        asyncio.run(feature.read_temperature(1, status=status))
