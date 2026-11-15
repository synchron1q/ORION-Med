# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS Recovery Monitor: statuses, finalization, gate effect, clearance-after-finding rule."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.cfms.config import RecoveryCriteria
from app.cfms.recovery import DATA_INCOMPLETE, RECOVERED, RECOVERING, REVIEW, evaluate_recovery
from conftest import feed

C = RecoveryCriteria(window_min=10, hrr60_min_bpm=12, baseline_tolerance_bpm=10, elevated_response_bpm=20, validity_h=24)
T0 = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
NOMINAL = {"heart_rate": 72, "spo2": 98, "cabin_co2": 2.0, "cabin_o2": 21.0, "cabin_pressure": 101.3}
CM1_AER, CM1_RES = "EX-D003-CM-1-AEROBIC-1", "EX-D003-CM-1-RESISTIVE-2"


def curve(fn, seconds: int, step: int = 2):
    return [(T0 + timedelta(seconds=t), fn(t)) for t in range(0, seconds + 1, step)]


def ev(samples, elapsed, pre=72.0, end=125.0, monitored=True):
    return evaluate_recovery(monitored=monitored, pre_hr=pre, end_hr=end, peak_hr=end, ended_at=T0,
                             now=T0 + timedelta(seconds=elapsed), samples=samples, stale_after_s=8, c=C)


def test_fast_drop_is_recovered_after_60_s():
    s = curve(lambda t: max(72.0, 125 - 7 * t), 120)
    assert ev(s, 30)["status"] == RECOVERING and not ev(s, 30)["final"]
    r = ev(s, 70)
    assert r["status"] == RECOVERED and r["final"] and r["hrr60"] == 53 and r["time_to_baseline_s"] <= 10


def test_slow_drop_after_elevated_response_needs_review():
    s = curve(lambda t: 125 - 0.1 * t, 120)
    r = ev(s, 61)
    assert r["status"] == REVIEW and r["final"] and r["hrr60"] < 12


def test_not_back_to_baseline_within_window_needs_review():
    s = curve(lambda t: max(95.0, 125 - 0.5 * t), 600)  # 60-s drop 30 bpm but plateau above 82
    assert ev(s, 300)["status"] == RECOVERING
    r = ev(s, 600)
    assert r["status"] == REVIEW and "within 10 min" in r["summary"]


def test_missing_data_is_never_normal():
    assert ev([], 61)["status"] == DATA_INCOMPLETE
    assert ev([], 20)["status"] == DATA_INCOMPLETE and not ev([], 20)["final"]
    assert ev(curve(lambda t: 80.0, 120), 70, end=None)["status"] == DATA_INCOMPLETE
    assert ev(curve(lambda t: 80.0, 120), 70, monitored=False)["status"] == DATA_INCOMPLETE


def test_no_elevated_response_is_not_flagged_for_small_drop():
    s = curve(lambda t: 78.0, 120)
    assert ev(s, 61, end=80)["status"] == RECOVERED


def _session_with_end_hr(core, clock, end_hr: float, after: list[float]):
    """CM-1 session with manual telemetry: start at 72 bpm, end at end_hr, then the given HR every 5 s."""
    f = core.fitness
    feed(core, clock, NOMINAL)
    f.start_session(CM1_AER)
    clock.advance(60)
    feed(core, clock, {**NOMINAL, "heart_rate": end_hr})
    f.complete_session(CM1_AER)
    for hr in after:
        clock.advance(5)
        feed(core, clock, {**NOMINAL, "heart_rate": hr})
        f.tick()


def test_review_requires_a_clearance_recorded_after_the_finding(cfms_core, clock):
    f = cfms_core.fitness
    early = f.grant_clearance(crew_id="CM-1", exercise_type="RESISTIVE", issued_by="Flight surgeon (SIMULATED)",
                              valid_until=cfms_core.now() + timedelta(hours=8))
    _session_with_end_hr(cfms_core, clock, 105, [105, 104, 104, 104, 104, 104, 104, 104, 104, 104, 104, 104, 104])
    det = f.session_detail(CM1_AER)
    assert det["context"]["recovery"]["status"] == REVIEW and det["context"]["recovery"]["final"]
    assert any("Recovery REVIEW" in e["message"] for e in cfms_core.timeline(80))
    feed(cfms_core, clock, NOMINAL)
    g = f.session_detail(CM1_RES)["gate"]
    assert g["status"] == "CLEARANCE_REQUIRED" and "RECOVERY_REVIEW" in {r["code"] for r in g["reasons"]}
    assert early["id"] not in str(g)  # the earlier clearance does not cover the new finding
    clock.advance(5)
    feed(cfms_core, clock, NOMINAL)
    new = f.grant_clearance(crew_id="CM-1", exercise_type="RESISTIVE", issued_by="Flight surgeon (SIMULATED)",
                            valid_until=cfms_core.now() + timedelta(hours=8))
    g = f.session_detail(CM1_RES)["gate"]
    assert g["status"] == "READY_PER_PLAN" and g["clearance"]["id"] == new["id"]
    # Stored result is final: later telemetry does not change it.
    assert f.session_detail(CM1_AER)["context"]["recovery"]["status"] == REVIEW


def test_sensor_loss_after_session_is_data_incomplete(cfms_core, clock):
    f = cfms_core.fitness
    _session_with_end_hr(cfms_core, clock, 120, [])
    clock.advance(65)
    feed(cfms_core, clock, {k: v for k, v in NOMINAL.items() if k != "heart_rate"})
    f.tick()
    rec = f.session_detail(CM1_AER)["context"]["recovery"]
    assert rec["status"] == DATA_INCOMPLETE and rec["final"]


def test_simulated_recovery_end_to_end(cfms_core, clock):
    core, f = cfms_core, cfms_core.fitness
    core.simulator.enabled = True
    for _ in range(5):
        clock.advance(1)
        core.tick()
    f.start_session(CM1_AER)
    for _ in range(20):
        clock.advance(1)
        core.tick()
    f.complete_session(CM1_AER)
    for _ in range(20):
        clock.advance(1)
        core.tick()
    view = f.recovery_view()
    item = view["items"][0]
    assert item["recovery"]["status"] == RECOVERING and len(item["curve"]) >= 3
    nxt = f.session_detail(CM1_RES)["gate"]
    assert "RECOVERY_IN_PROGRESS" in {r["code"] for r in nxt["reasons"]}
    for _ in range(45):
        clock.advance(1)
        core.tick()
    rec = f.session_detail(CM1_AER)["context"]["recovery"]
    assert rec["status"] == RECOVERED and rec["final"] and rec["hrr60"] >= 12
    nxt = f.session_detail(CM1_RES)["gate"]
    assert not {r["code"] for r in nxt["reasons"]} & {"RECOVERY_IN_PROGRESS", "RECOVERY_REVIEW", "RECOVERY_DATA_INCOMPLETE"}
    summary = f.summary({"alerts": core.list_alerts(), "parameters": core.parameter_states()})
    assert summary["recovery"][0]["status"] == RECOVERED
    latest = {x["crew_id"]: x for x in view["latest_by_crew"]}
    assert latest["CM-2"]["recovery"] is None
    assert view["criteria"]["provenance"] == "DEMONSTRATION"


def test_unmonitored_crew_recovery_is_data_incomplete_without_extra_gate_reason(cfms_core, clock):
    f = cfms_core.fitness
    feed(cfms_core, clock, NOMINAL)
    f.grant_clearance(crew_id="CM-2", exercise_type="AEROBIC", issued_by="Flight surgeon (SIMULATED)",
                      valid_until=cfms_core.now() + timedelta(hours=2))
    f.start_session("EX-D003-CM-2-AEROBIC-1")
    clock.advance(60)
    f.complete_session("EX-D003-CM-2-AEROBIC-1")
    f.tick()
    rec = f.session_detail("EX-D003-CM-2-AEROBIC-1")["context"]["recovery"]
    assert rec["status"] == DATA_INCOMPLETE and "No biosensor" in rec["summary"]
    feed(cfms_core, clock, NOMINAL)
    g = f.session_detail("EX-D003-CM-2-RESISTIVE-2")["gate"]
    assert {r["code"] for r in g["reasons"]} == {"NO_BIOSENSOR"}


@pytest.mark.parametrize("bad", [{"window_min": 1}])
def test_recovery_window_validation(tmp_path, settings, bad):
    import shutil

    import yaml

    from app.cfms.config import load_fitness_config
    from app.core.registry import ConfigError
    cfg = tmp_path / "c"
    shutil.copytree(settings.config_dir, cfg)
    d = yaml.safe_load((cfg / "fitness.yaml").read_text(encoding="utf-8"))
    d["recovery"].update(bad)
    (cfg / "fitness.yaml").write_text(yaml.safe_dump(d), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_fitness_config(cfg, ["CM-1", "CM-2", "CM-3", "CM-4"])
