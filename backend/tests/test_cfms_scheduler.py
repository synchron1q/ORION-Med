# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS scheduler: determinism, idempotency, conflicts, rescheduling, single source of truth."""
from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, inspect, select

from app.cfms.models import ExerciseSession, RuntimeActivity, ScheduleDecision
from app.cfms.scheduler import OCCUPYING, crew_conflict, device_conflict, plan_conflict
from app.cfms.service import CfmsConflict
from app.services.core import HevCore

AER1 = "EX-D003-CM-1-AEROBIC-1"


def snapshot(core: HevCore) -> dict[str, tuple]:
    return {s["id"]: (s["status"], s["planned_start"], s["device_id"]) for s in core.fitness.schedule()}


def count(core: HevCore, model) -> int:
    with core.Session() as s:
        return s.scalar(select(func.count()).select_from(model))


def decisions(core: HevCore, sid: str) -> list[dict]:
    return list(reversed(core.fitness.decisions(sid)))


def test_cfms_disabled_by_default(core):
    assert core.fitness is None
    assert not [t for t in inspect(core.engine).get_table_names() if t.startswith("cfms_")]


def test_initial_plan_is_deterministic(settings, clock, tmp_path):
    cores = []
    for name in ("a.db", "b.db"):
        settings.database_path = tmp_path / name
        settings.cfms_enabled = True
        cores.append(HevCore(settings, now_fn=clock))
    try:
        a, b = (snapshot(c) for c in cores)
        assert a == b and len(a) == 24
        da = [(d["action"], d["session_id"], d["to_start"], d["to_device"]) for d in cores[0].fitness.decisions(limit=500)]
        db = [(d["action"], d["session_id"], d["to_start"], d["to_device"]) for d in cores[1].fitness.decisions(limit=500)]
        assert da == db
    finally:
        for c in cores:
            c.engine.dispose()


def test_replan_is_idempotent(cfms_core):
    before = (snapshot(cfms_core), count(cfms_core, ScheduleDecision), count(cfms_core, ExerciseSession))
    for _ in range(3):
        assert cfms_core.fitness.replan("TEST")["changes"] == 0
    assert (snapshot(cfms_core), count(cfms_core, ScheduleDecision), count(cfms_core, ExerciseSession)) == before


def test_restart_with_unchanged_plan_creates_no_duplicates(settings, clock):
    settings.cfms_enabled = True
    a = HevCore(settings, now_fn=clock)
    snap, n_dec, n_ses = snapshot(a), count(a, ScheduleDecision), count(a, ExerciseSession)
    a.engine.dispose()
    b = HevCore(settings, now_fn=clock)
    try:
        assert snapshot(b) == snap
        assert count(b, ScheduleDecision) == n_dec and count(b, ExerciseSession) == n_ses
    finally:
        b.engine.dispose()


def test_placements_respect_plan_devices_and_crew_gaps(cfms_core):
    f = cfms_core.fitness
    with cfms_core.Session() as s:
        ctx = f._context(s, cfms_core.now())
        _, states = f._sessions(s, cfms_core.now())
    placed = [x for x in states if x.status in OCCUPYING]
    assert placed
    for x in placed:
        assert plan_conflict(ctx, x.crew_id, x.start, x.end, x.day_index) is None
        assert device_conflict(ctx, x.device_id, x.start, x.end, placed, x.id) is None
        assert crew_conflict(ctx, x.crew_id, x.start, x.end, placed, x.id) is None
        assert (x.start - ctx.met_start).total_seconds() % (15 * 60) == 0


def test_eva_day_has_no_window_and_records_reason(cfms_core):
    sched = snapshot(cfms_core)
    for sid in ("EX-D004-CM-1-AEROBIC-1", "EX-D004-CM-3-RESISTIVE-2"):
        assert sched[sid][0] == "UNSCHEDULED"
        d = decisions(cfms_core, sid)[-1]
        assert d["action"] == "UNSCHEDULABLE" and d["conflict_ref"] == "EVA-1" and "EVA" in d["reason"]
    assert sched["EX-D004-CM-2-AEROBIC-1"][0] == "PLANNED"  # not on the EVA crew


def test_runtime_conflict_moves_session_with_full_history(cfms_core):
    f = cfms_core.fitness
    old = snapshot(cfms_core)[AER1]
    res = f.add_activity(activity_type="MANEUVER", title="Unplanned attitude maneuver", crew=["ALL"],
                         start=cfms_core.now() + timedelta(minutes=20), duration_min=20, source="MANUAL")
    assert res["activity"]["id"] == "RT-0001"
    moved = [d for d in res["replan"]["decisions"] if d["session_id"] == AER1]
    assert moved and moved[0]["action"] == "MOVED"
    d = moved[0]
    assert d["from_start"] == old[1] and d["to_start"] != old[1]
    assert d["conflict_ref"] == "RT-0001" and d["trigger"] == "PLAN_CHANGE RT-0001" and "MANEUVER" in d["reason"]
    new = snapshot(cfms_core)
    assert new[AER1][1] == d["to_start"]
    assert f.replan("TEST")["changes"] == 0
    # Removing the conflict does not move placed sessions back (no change without a reason);
    # only sessions that had no window at all may now be placed.
    after = f.cancel_activity("RT-0001")["replan"]["decisions"]
    assert {d["action"] for d in after} <= {"PLACED"}
    final = snapshot(cfms_core)
    assert all(final[k] == v for k, v in new.items() if v[0] == "PLANNED")


def test_baseline_lives_only_in_yaml(cfms_core):
    f = cfms_core.fitness
    assert count(cfms_core, RuntimeActivity) == 0
    with pytest.raises(CfmsConflict):
        f.cancel_activity("TCM-3")
    view = f.plan_view()
    assert {a["origin"] for a in view["activities"]} == {"BASELINE"}
    assert not any(a["editable"] for a in view["activities"])
    f.add_activity(activity_type="WORK", title="Payload task", crew=["CM-2"], start=cfms_core.now() + timedelta(hours=30),
                   duration_min=30)
    view = f.plan_view()
    rt = [a for a in view["activities"] if a["origin"] == "RUNTIME"]
    assert len(rt) == 1 and rt[0]["editable"] and rt[0]["id"].startswith("RT-")


def test_device_fault_then_restore(cfms_core):
    f = cfms_core.fitness
    f.set_equipment("RES-01", "FAULT", "Simulated cable fault")
    sched = snapshot(cfms_core)
    res = [v for k, v in sched.items() if "RESISTIVE" in k]
    assert res and all(v[0] == "UNSCHEDULED" for v in res)
    d = decisions(cfms_core, "EX-D003-CM-1-RESISTIVE-2")[-1]
    assert d["action"] == "UNSCHEDULABLE" and d["conflict_code"] == "DEVICE_STATUS" and d["from_device"] == "RES-01"
    f.set_equipment("RES-01", "OPERATIONAL")
    sched = snapshot(cfms_core)
    assert all(v[0] == "PLANNED" for k, v in sched.items() if "RESISTIVE" in k and "D004-CM-1" not in k and "D004-CM-3" not in k)
    assert decisions(cfms_core, "EX-D003-CM-1-RESISTIVE-2")[-1]["action"] == "PLACED"
    # An aerobic session falls back to another device class instead of losing the window.
    f.set_equipment("ERG-01", "FAULT")
    assert all(v[2] != "ERG-01" for v in snapshot(cfms_core).values())


def test_missed_session_is_rescheduled_until_limit(cfms_core, clock):
    f = cfms_core.fitness
    for attempt in (1, 2):
        start = cfms_core.fitness.session_detail(AER1)["planned_start"]
        clock.t = _parse(start) + timedelta(minutes=16)
        f.tick()
        det = f.session_detail(AER1)
        assert det["status"] in ("PLANNED", "NOTIFIED") and det["attempt"] == attempt
        actions = [d["action"] for d in det["decisions"][:2]]
        assert actions == ["RESCHEDULED", "MISSED"]
        assert _parse(det["planned_start"]) > clock.t
    clock.t = _parse(f.session_detail(AER1)["planned_start"]) + timedelta(minutes=16)
    f.tick()
    det = f.session_detail(AER1)
    assert det["status"] == "MISSED" and "limit" in det["decisions"][0]["reason"]
    assert f.replan("TEST")["changes"] == 0


def test_upcoming_session_notification(cfms_core):
    f = cfms_core.fitness
    f.tick()
    assert f.session_detail(AER1)["status"] == "NOTIFIED"
    msgs = [e["message"] for e in cfms_core.timeline(80) if e["category"] == "FITNESS"]
    assert any(m.startswith("Upcoming exercise: CM-1") for m in msgs)


def test_crew_request_earliest(cfms_core):
    f = cfms_core.fitness
    sid = "EX-D003-CM-2-AEROBIC-1"
    out = f.request_earliest(sid)
    assert out["decision"]["action"] == "CREW_REQUEST"
    assert out["session"]["planned_start"] < out["decision"]["from_start"]
    with pytest.raises(CfmsConflict):
        f.request_earliest("EX-D003-CM-1-RESISTIVE-2")  # maneuver and meal buffers leave no earlier window
    assert f.replan("TEST")["changes"] == 0


def test_baseline_revision_triggers_deterministic_replan(settings, clock, tmp_path):
    cfg = tmp_path / "config"
    shutil.copytree(settings.config_dir, cfg)
    settings.config_dir, settings.cfms_enabled = cfg, True
    a = HevCore(settings, now_fn=clock)
    old = snapshot(a)[AER1]
    a.engine.dispose()
    plan = cfg / "mission_plan.yaml"
    plan.write_text(plan.read_text(encoding="utf-8").replace(
        "events:\n", "events:\n  - {id: OPS-X, type: CRITICAL_OPS, title: \"Docking rehearsal\", start_met_h: 77.0, duration_min: 30, crew: [ALL]}\n", 1),
        encoding="utf-8")
    b = HevCore(settings, now_fn=clock)
    try:
        d = decisions(b, AER1)[-1]
        assert d["action"] == "MOVED" and d["trigger"] == "PLAN_REVISION" and d["conflict_ref"] == "OPS-X"
        assert d["from_start"] == old[1] and d["plan_hash"] == b.fitness.plan.content_hash
        assert any("revision changed" in e["message"] for e in b.timeline(80))
        assert count(b, RuntimeActivity) == 0
    finally:
        b.engine.dispose()


def _parse(s: str):
    from datetime import datetime
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
