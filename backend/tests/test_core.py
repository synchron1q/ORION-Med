# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.core.settings import Settings
from app.engine.alert_machine import TransitionError
from app.models import AlertHistory, CountermeasureExecution, TelemetryRecord
from app.services.core import HevCore, TelemetryInput

from conftest import alerts_by_rule, feed


def test_validation_rejects_bad_input(core, clock):
    bad = [
        TelemetryInput("unknown", 1.0),
        TelemetryInput("heart_rate", 70.0, unit="Hz"),
        TelemetryInput("heart_rate", None),
        TelemetryInput("heart_rate", float("nan")),
        TelemetryInput("heart_rate", 70.0, timestamp=clock() + timedelta(minutes=5)),
        TelemetryInput("hydration", 50.0),
        TelemetryInput("heart_rate", 70.0, source="MAGIC"),
    ]
    result = core.ingest(bad)
    assert result["accepted"] == 0 and len(result["rejected"]) == len(bad)


def test_out_of_range_value_is_sensor_fault_not_measurement(core, clock):
    feed(core, clock, {"heart_rate": 400})
    a = alerts_by_rule(core)
    assert "FAULT-heart_rate" in a and "TH-heart_rate" not in a
    hr = next(p for p in core.parameter_states() if p["id"] == "heart_rate")
    assert hr["status"] == "SENSOR_FAULT" and hr["value"] is None


def test_threshold_alert_escalation_and_ack(core, clock):
    feed(core, clock, {"heart_rate": 115}, source="SIMULATED")
    a = alerts_by_rule(core)["TH-heart_rate"]
    assert a["severity"] == "CAUTION" and a["simulated"] and a["protocol_id"] == "CM-CARDIO-01" and a["zone"] == "cardiovascular"
    core.acknowledge(a["id"])
    clock.advance(1)
    feed(core, clock, {"heart_rate": 140}, source="SIMULATED")
    a = alerts_by_rule(core)["TH-heart_rate"]
    assert a["severity"] == "WARNING" and not a["acknowledged"], "escalation must re-alarm"
    acked = core.acknowledge(a["id"])
    assert acked["lifecycle"] == "ACTIVE" and acked["severity"] == "WARNING", "ACK must never clear a warning"
    assert "ACKNOWLEDGED" in acked["states"]


def test_recovery_hold_and_clear(core, clock):
    feed(core, clock, {"cabin_co2": 7.0})
    alert_id = alerts_by_rule(core)["TH-cabin_co2"]["id"]
    with pytest.raises(TransitionError):
        core.resolve(alert_id)
    clock.advance(1)
    feed(core, clock, {"cabin_co2": 3.8})  # below limit but inside 0.5 hysteresis -> hold
    assert alerts_by_rule(core)["TH-cabin_co2"]["lifecycle"] == "ACTIVE"
    clock.advance(1)
    feed(core, clock, {"cabin_co2": 2.5})
    assert alerts_by_rule(core)["TH-cabin_co2"]["lifecycle"] == "RECOVERY"
    for _ in range(5):
        clock.advance(1)
        feed(core, clock, {"cabin_co2": 2.4})
    a = alerts_by_rule(core)["TH-cabin_co2"]
    assert a["resolution_verified"] and a["can_clear"]
    cleared = core.resolve(alert_id)
    assert cleared["lifecycle"] == "CLEARED"
    assert "TH-cabin_co2" not in alerts_by_rule(core)
    detail = core.alert_detail(alert_id)
    assert [h["event_type"] for h in detail["history"]][-1] == "CLEARED"
    assert detail["history"][0]["event_type"] == "RAISED"


def test_repeated_alert_creates_new_instance(core, clock):
    feed(core, clock, {"cabin_co2": 7.0})
    first = alerts_by_rule(core)["TH-cabin_co2"]["id"]
    for _ in range(7):
        clock.advance(1)
        feed(core, clock, {"cabin_co2": 2.0})
    core.resolve(first)
    clock.advance(1)
    feed(core, clock, {"cabin_co2": 7.0})
    second = alerts_by_rule(core)["TH-cabin_co2"]
    assert second["id"] != first
    assert "repeat #2" in core.alert_detail(second["id"])["history"][0]["detail"]


def test_countermeasure_steps_recorded(core, clock):
    feed(core, clock, {"cabin_co2": 7.0})
    a = alerts_by_rule(core)["TH-cabin_co2"]
    out = core.confirm_step(a["id"], 0)
    assert out["cm_status"] == "IN_PROGRESS" and out["cm_steps_done"] == [0]
    n = len(core.reg.protocols["CM-ECLSS-01"].steps)
    for i in range(1, n):
        out = core.confirm_step(a["id"], i)
    assert out["cm_status"] == "COMPLETED" and out["lifecycle"] == "ACTIVE"
    with core.Session() as s:
        assert s.scalar(select(func.count()).select_from(CountermeasureExecution)) == n


def test_stale_data_never_assumed_normal(core, clock):
    feed(core, clock, {"spo2": 98})
    clock.advance(9)
    core.tick_monitor()
    a = alerts_by_rule(core)
    assert "STALE-spo2" in a and a["STALE-spo2"]["kind"] == "DATA_STALE"
    spo2 = next(p for p in core.parameter_states() if p["id"] == "spo2")
    assert spo2["status"] == "STALE" and spo2["band"] is None


def test_never_received_sensor_goes_stale(core, clock):
    clock.advance(10)
    core.tick_monitor()
    assert "STALE-heart_rate" in alerts_by_rule(core)
    hr = next(p for p in core.parameter_states() if p["id"] == "heart_rate")
    assert hr["status"] == "NO_DATA"


def test_sensor_fault_and_recovery(core, clock):
    core.ingest([TelemetryInput("heart_rate", None, "bpm", clock(), "SENSOR", "FAULT", metadata={"reason": "lead off"})])
    a = alerts_by_rule(core)["FAULT-heart_rate"]
    assert "SENSOR_FAULT" in a["states"] and "lead off" in a["message"]
    for _ in range(7):
        clock.advance(1)
        feed(core, clock, {"heart_rate": 70})
    assert "FAULT-heart_rate" not in alerts_by_rule(core)
    assert "FAULT-heart_rate" in alerts_by_rule(core, include_cleared=True)


def test_missing_data_cannot_resolve_threshold_alert(core, clock):
    feed(core, clock, {"heart_rate": 140})
    clock.advance(30)
    core.tick_monitor()
    a = alerts_by_rule(core)
    assert a["TH-heart_rate"]["lifecycle"] == "ACTIVE" and "STALE-heart_rate" in a


def test_out_of_order_sample_not_evaluated(core, clock):
    feed(core, clock, {"heart_rate": 70})
    old = clock() - timedelta(seconds=30)
    core.ingest([TelemetryInput("heart_rate", 150, "bpm", old, "SENSOR")])
    assert "TH-heart_rate" not in alerts_by_rule(core)
    with core.Session() as s:
        late = s.scalars(select(TelemetryRecord).where(TelemetryRecord.value == 150)).one()
        assert late.meta == {"late": True}


def test_multiple_simultaneous_alerts_sorted(core, clock):
    feed(core, clock, {"heart_rate": 140, "cabin_co2": 4.5, "hrv": 20})
    sev = [a["severity"] for a in core.list_alerts()]
    assert sev == sorted(sev, key=["WARNING", "CAUTION", "ADVISORY"].index)
    assert len(sev) == 3
    assert core.dashboard()["master"]["warning_unacked"]


def test_ridge_correlation_is_advisory_context(core, clock):
    for _ in range(3):
        feed(core, clock, {"cabin_co2": 5.0, "heart_rate": 92})
        core.tick_monitor()
        clock.advance(1)
    a = alerts_by_rule(core)["RIDGE-CO2-COG"]
    assert a["kind"] == "CORRELATION" and a["severity"] == "ADVISORY"
    assert "not proof of causation" in a["message"]
    assert {f["factor"] for f in a["factors"]} >= {"cabin_co2", "heart_rate"}
    for _ in range(15):
        feed(core, clock, {"cabin_co2": 2.0, "heart_rate": 72})
        core.tick_monitor()
        clock.advance(1)
    assert "RIDGE-CO2-COG" not in alerts_by_rule(core)


def test_persistence_after_restart(settings, clock):
    c1 = HevCore(settings, now_fn=clock)
    c1.simulator.enabled = False
    feed(c1, clock, {"cabin_co2": 7.0, "heart_rate": 75})
    alert_id = alerts_by_rule(c1)["TH-cabin_co2"]["id"]
    c1.acknowledge(alert_id)
    c1.sync.set_link(False)
    c1.engine.dispose()

    clock.advance(2)
    c2 = HevCore(settings, now_fn=clock)
    a = alerts_by_rule(c2)["TH-cabin_co2"]
    assert a["id"] == alert_id and a["acknowledged"] and a["lifecycle"] == "ACTIVE"
    assert next(p for p in c2.parameter_states() if p["id"] == "heart_rate")["value"] == 75
    assert c2.sync.link_up is False
    with c2.Session() as s:
        assert s.scalar(select(func.count()).select_from(AlertHistory)) >= 2
    c2.engine.dispose()


def test_pvt_feeds_telemetry_and_history(core, clock):
    r = core.submit_pvt([250, 300, 520], misses=1, false_starts=1, duration_s=10)
    assert r["mean_rt_ms"] == 356.7 and r["lapses"] == 1 and r["stimuli"] == 4
    pvt = next(p for p in core.parameter_states() if p["id"] == "pvt_mean_rt")
    assert pvt["value"] == 356.7 and pvt["source"] == "CREW_INPUT"
    assert alerts_by_rule(core)["TH-pvt_mean_rt"]["severity"] == "ADVISORY"
    clock.advance(60)
    core.submit_pvt([240, 260], 0, 0, 10)
    hist = core.pvt_history()
    assert hist["baseline_mean_rt_ms"] == 356.7 and hist["latest_delta_ms"] == -106.7
    with pytest.raises(ValueError):
        core.submit_pvt([50], 0, 0, 10)


def test_psych_private_by_default_not_synced(core, clock):
    from app.models import SyncQueueItem

    core.submit_psych(3, 2, 4, 3, "", True)
    core.submit_psych(4, 2, 2, 4, "", False)
    with core.Session() as s:
        types = s.scalars(select(SyncQueueItem.event_type)).all()
    assert types.count("PSYCH_ASSESSMENT_SHARED") == 1
    assert len(core.psych_history()) == 2
