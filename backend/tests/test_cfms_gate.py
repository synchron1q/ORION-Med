# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS Safety Gate, scoped Medical Clearance, exercise profile, alert non-suppression."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.cfms.config import ExerciseProfile
from app.cfms.gate import BLOCKED, CLEARANCE_REQUIRED, READY, evaluate_gate, evaluate_profile
from app.cfms.service import CfmsConflict
from conftest import feed

NOMINAL = {"heart_rate": 72, "spo2": 98, "cabin_co2": 2.0, "cabin_o2": 21.0, "cabin_pressure": 101.3}
CM1_AER = "EX-D003-CM-1-AEROBIC-1"
CM2_AER = "EX-D003-CM-2-AEROBIC-1"


def gate(core, sid):
    return core.fitness.session_detail(sid)["gate"]


def codes(g):
    return {r["code"] for r in g["reasons"]}


def grant(core, crew="CM-2", ex="AEROBIC", hours=2.0, **kw):
    return core.fitness.grant_clearance(crew_id=crew, exercise_type=ex, issued_by="Flight surgeon (SIMULATED)",
                                        valid_until=core.now() + timedelta(hours=hours), **kw)


def test_monitored_crew_with_fresh_data_is_ready_per_plan(cfms_core, clock):
    feed(cfms_core, clock, NOMINAL)
    g = gate(cfms_core, CM1_AER)
    assert g["status"] == READY and g["clearance"] is None
    assert "not a medical authorization" in g["disclaimer"]


CABIN = {k: v for k, v in NOMINAL.items() if k.startswith("cabin")}


def test_incomplete_data_is_never_treated_as_normal(cfms_core, clock):
    feed(cfms_core, clock, CABIN)  # no biosensor data for CM-1
    g = gate(cfms_core, CM1_AER)
    assert g["status"] == CLEARANCE_REQUIRED and "DATA_INCOMPLETE" in codes(g)


def test_unmonitored_cabin_blocks_even_with_clearance(cfms_core, clock):
    feed(cfms_core, clock, {"heart_rate": 72, "spo2": 98})  # no cabin data at all
    grant(cfms_core, crew="CM-2")
    for sid in (CM1_AER, CM2_AER):
        g = gate(cfms_core, sid)
        assert g["status"] == BLOCKED and "CABIN_DATA_INCOMPLETE" in codes(g)


def test_unmonitored_crew_needs_a_scoped_clearance(cfms_core, clock):
    feed(cfms_core, clock, NOMINAL)
    assert gate(cfms_core, CM2_AER)["status"] == CLEARANCE_REQUIRED
    grant(cfms_core, ex="RESISTIVE")                      # other exercise type
    grant(cfms_core, crew="CM-3")                         # other crew member
    assert gate(cfms_core, CM2_AER)["status"] == CLEARANCE_REQUIRED
    c = grant(cfms_core, hours=2)
    g = gate(cfms_core, CM2_AER)
    assert g["status"] == READY and g["clearance"]["id"] == c["id"]
    cfms_core.fitness.revoke_clearance(c["id"], "Test")
    assert gate(cfms_core, CM2_AER)["status"] == CLEARANCE_REQUIRED


def test_clearance_must_cover_the_whole_session_window(cfms_core, clock):
    feed(cfms_core, clock, NOMINAL)
    grant(cfms_core, hours=0.4)  # ends before the 76:45-77:15 session ends
    assert gate(cfms_core, CM2_AER)["status"] == CLEARANCE_REQUIRED


@pytest.mark.parametrize("kwargs", [
    {"hours": 25},                                    # longer than max_validity_h (24)
    {"hours": -1},                                    # already expired
    {"crew": "CM-9"},
    {"ex": "ANY"},
    {"hours": 2, "valid_from": datetime(2026, 11, 13, tzinfo=timezone.utc)},  # back-dated
])
def test_clearance_validation(cfms_core, kwargs):
    with pytest.raises(ValueError):
        grant(cfms_core, **kwargs)


def test_clearance_never_overrides_a_critical_alert(cfms_core, clock):
    feed(cfms_core, clock, {**NOMINAL, "heart_rate": 150})  # global WARNING (unchanged limit 130)
    grant(cfms_core, crew="CM-1")
    grant(cfms_core, crew="CM-2")
    for sid in (CM1_AER, CM2_AER):
        g = gate(cfms_core, sid)
        assert g["status"] == BLOCKED and "MASTER_WARNING" in codes(g)
        assert "CLEARANCE_NOT_APPLICABLE" in codes(g)


def test_cabin_caution_blocks_every_crew_member(cfms_core, clock):
    feed(cfms_core, clock, {**NOMINAL, "cabin_co2": 5.0})
    grant(cfms_core, crew="CM-2")
    g = gate(cfms_core, CM2_AER)
    assert g["status"] == BLOCKED and "CABIN_CAUTION" in codes(g)


def test_equipment_and_plan_conflicts_block():
    now = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
    common = dict(crew_id="CM-1", monitored_crew_id="CM-1", exercise_type="AEROBIC", start=now, end=now + timedelta(minutes=30),
                  alerts=[], parameters=[{"id": "heart_rate", "status": "OK", "value": 70}, {"id": "spo2", "status": "OK", "value": 98}],
                  required_parameters=("heart_rate", "spo2"), required_cabin_parameters=())
    assert evaluate_gate(**common, device_id="ERG-01", device_status="OPERATIONAL")["status"] == READY
    assert evaluate_gate(**common, device_id="ERG-01", device_status="DEGRADED")["status"] == BLOCKED
    assert evaluate_gate(**common, device_id=None)["status"] == BLOCKED

    class C:
        code, ref, text = "PHASE", "PH-LOI", "Mission phase forbids exercise"
    assert evaluate_gate(**common, device_id="ERG-01", device_status="OPERATIONAL", plan_conflict=C())["status"] == BLOCKED


def test_start_requires_ready_gate_and_open_window(cfms_core, clock):
    f = cfms_core.fitness
    feed(cfms_core, clock, NOMINAL)
    with pytest.raises(CfmsConflict) as exc:
        f.start_session(CM2_AER)
    assert exc.value.detail["gate"]["status"] == CLEARANCE_REQUIRED
    grant(cfms_core, crew="CM-2")
    assert f.start_session(CM2_AER)["status"] == "IN_PROGRESS"
    with pytest.raises(CfmsConflict, match="Start window opens"):
        f.start_session("EX-D003-CM-1-RESISTIVE-2")


def test_exercise_profile_never_suppresses_global_alerts(cfms_core, clock):
    f = cfms_core.fitness
    hr_limit = cfms_core.reg.parameters["heart_rate"].thresholds.warning_high
    feed(cfms_core, clock, NOMINAL)
    started = f.start_session(CM1_AER)
    assert started["status"] == "IN_PROGRESS" and started["profile_id"] == "EXP-AEROBIC-DEMO"
    clock.advance(60)
    feed(cfms_core, clock, {**NOMINAL, "heart_rate": 135})
    hr_alerts = [a for a in cfms_core.list_alerts() if a["parameter"] == "heart_rate"]
    assert hr_alerts and hr_alerts[0]["severity"] == "WARNING"       # global limit still applies
    assert cfms_core.reg.parameters["heart_rate"].thresholds.warning_high == hr_limit
    f.tick()
    summary = f.summary({"alerts": cfms_core.list_alerts(), "parameters": cfms_core.parameter_states()})
    prof = summary["in_progress"][0]["profile"]
    assert prof["heart_rate"]["band"] == "IN_TARGET" and prof["provenance"] == "DEMONSTRATION"
    assert summary["alert_context"][hr_alerts[0]["id"]] == CM1_AER
    log = [e["message"] for e in cfms_core.timeline(80) if e["category"] == "FITNESS"]
    assert any("NOT suppressed" in m for m in log)
    assert any("EXP-AEROBIC-DEMO applied" in m for m in log)
    done = f.complete_session(CM1_AER)
    assert done["status"] == "COMPLETED" and done["peak_hr"] == 135


def test_profile_bands():
    p = ExerciseProfile("P", "P", {"target_low": 100, "target_high": 145, "review_above": 160, "stop_above": 175},
                        {"review_below": 93, "stop_below": 90})

    def band(hr, spo2=98, status="OK"):
        params = [{"id": "heart_rate", "status": status, "value": hr}, {"id": "spo2", "status": "OK", "value": spo2}]
        return evaluate_profile(p, params, True)["overall"]
    assert band(120) == "IN_TARGET"
    assert band(90) == "BELOW_TARGET"
    assert band(150) == "ABOVE_TARGET"
    assert band(165) == "REVIEW"
    assert band(180) == "STOP_RECOMMENDED"
    assert band(120, spo2=89) == "STOP_RECOMMENDED"
    assert band(120, status="STALE") == "DATA_INCOMPLETE"
    assert evaluate_profile(p, [], False)["overall"] == "DATA_INCOMPLETE"


def test_simulated_exercise_load_goes_through_normal_alerting(cfms_core, clock):
    """Simulator + confirmed session: global CAUTION fires (limits unchanged), R.I.D.G.E. explains it."""
    core, f = cfms_core, cfms_core.fitness
    core.simulator.enabled = True
    for _ in range(5):
        clock.advance(1)
        core.tick()
    f.start_session(CM1_AER)
    for _ in range(20):
        clock.advance(1)
        core.tick()
    alerts = {a["rule_id"]: a for a in core.list_alerts()}
    hr = next(a for a in alerts.values() if a["parameter"] == "heart_rate" and a["kind"] == "THRESHOLD")
    assert hr["severity"] == "CAUTION"
    assert "RIDGE-HR-ACT" in alerts
    st = {"alerts": core.list_alerts(), "parameters": core.parameter_states()}
    s = f.summary(st)
    assert s["in_progress"][0]["profile"]["heart_rate"]["band"] == "IN_TARGET"
    assert s["alert_context"][hr["id"]] == CM1_AER
    # The next session of the same crew member is blocked while the caution is active.
    nxt = f.session_detail("EX-D003-CM-1-RESISTIVE-2")["gate"]
    assert nxt["status"] == BLOCKED and "MEDICAL_CAUTION" in codes(nxt)
    f.complete_session(CM1_AER)
    for _ in range(20):
        clock.advance(1)
        core.tick()
    assert core.state["heart_rate"].last_valid_value < 90  # load removed after the session
