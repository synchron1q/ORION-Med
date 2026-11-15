# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS service: persistence, session lifecycle, notifications, mission log, sync queue.

Integrates with HevCore only through its public hooks (lock, Session, now, log,
enqueue, list_alerts, parameter_states, reg.crew, crew_id). HevCore thresholds
and the alert state machine are never modified, and no alert is suppressed.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import desc, or_, select
from sqlalchemy.orm import Session

from app.cfms.config import ALL, DEVICE_STATUSES, load_fitness_config, load_mission_plan, met_label
from app.cfms.gate import BLOCKED, GATE_DISCLAIMER, READY, ClearanceView, evaluate_gate, evaluate_profile
from app.cfms.recovery import DATA_INCOMPLETE, RECOVERING, REVIEW, evaluate_recovery
from app.cfms.models import CfmsBase, EquipmentState, ExerciseSession, MedicalClearance, RuntimeActivity, ScheduleDecision
from app.cfms.scheduler import (
    IN_PROGRESS, MOVABLE, NOTIFIED, OCCUPYING, PLANNED, TERMINAL, UNSCHEDULED, Activity, Decision, Outcome,
    PlanningContext, SessionState, crew_conflict, day_of, device_conflict, expand_plan, plan_conflict, reconcile,
    reschedule_earliest,
)
from app.models import Mission, MissionLogEntry, TelemetryRecord, new_id

if TYPE_CHECKING:
    from app.services.core import HevCore

SOURCES = ("MANUAL", "SIMULATED", "KRPC")
ACTIVE_VIEW = (PLANNED, NOTIFIED, IN_PROGRESS, UNSCHEDULED)
LOG_CATEGORY = "FITNESS"


def iso(dt: datetime | None) -> str | None:
    from app.services.core import iso as core_iso
    return core_iso(dt)


class CfmsConflict(Exception):
    """Request not possible in the current state (HTTP 409)."""

    def __init__(self, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.detail = detail or {}


class FitnessService:
    def __init__(self, core: "HevCore"):
        self.core = core
        self.crew = {c["id"]: c for c in core.reg.crew}
        self.cfg = load_fitness_config(core.settings.config_dir, self.crew)
        self.plan = load_mission_plan(core.settings.config_dir, self.crew, self.cfg)
        CfmsBase.metadata.create_all(core.engine)
        with core.Session() as s:
            self.met_start: datetime = s.get(Mission, core.mission_id).met_start_utc
        self._last_replan: datetime | None = None
        self._profile_band: dict[str, str] = {}
        self._alarm_ctx: dict[str, Any] | None = None
        prev = core.get_runtime("cfms.plan_hash")
        trigger = "STARTUP"
        if prev is None:
            core.log(LOG_CATEGORY, f"CFMS enabled. Baseline Mission Plan {self.plan.plan_id} rev {self.plan.revision} "
                                   f"(hash {self.plan.content_hash}) loaded from config/mission_plan.yaml (SIMULATED)", "CFMS")
        elif prev != self.plan.content_hash:
            trigger = "PLAN_REVISION"
            core.log(LOG_CATEGORY, f"Baseline Mission Plan revision changed (hash {prev} -> {self.plan.content_hash}); "
                                   "replanning deterministically", "CFMS")
        core.set_runtime("cfms.plan_hash", self.plan.content_hash)
        self.replan(trigger)
        self._restore_alarm_ctx()

    # ----------------------------------------------------------- helpers
    @property
    def monitored_crew_id(self) -> str | None:
        return self.core.crew_id

    def met(self, t: datetime | None) -> str:
        return met_label(self.met_start, t)

    def _device_status(self, s: Session) -> dict[str, str]:
        out = {d.id: d.initial_status for d in self.cfg.devices.values()}
        for row in s.scalars(select(EquipmentState)).all():
            if row.device_id in out:
                out[row.device_id] = row.status
        return out

    def _context(self, s: Session, now: datetime) -> PlanningContext:
        hi = now + timedelta(hours=self.cfg.policy.horizon_h + 24)
        acts = expand_plan(self.plan, self.met_start, now - timedelta(days=1), hi)
        rows = s.scalars(select(RuntimeActivity).where(RuntimeActivity.status == "ACTIVE",
                                                       RuntimeActivity.end >= now - timedelta(days=2))).all()
        acts += [Activity(r.id, r.activity_type, r.title, tuple(r.crew), r.start, r.end, r.device_id, r.source) for r in rows]
        return PlanningContext(now, self.met_start, self.cfg, self.plan, acts, self._device_status(s))

    def _duration(self, exercise_type: str) -> timedelta:
        ex = self.cfg.exercise_types.get(exercise_type)
        return timedelta(minutes=ex.duration_min if ex else 30)

    def _sessions(self, s: Session, now: datetime) -> tuple[dict[str, ExerciseSession], list[SessionState]]:
        first_day = day_of(self.met_start, now) - 1
        rows = s.scalars(select(ExerciseSession).where(or_(ExerciseSession.day_index >= first_day,
                                                           ExerciseSession.status.in_(ACTIVE_VIEW)))).all()
        states: list[SessionState] = []
        for r in rows:
            st, en = r.planned_start, r.planned_end
            if r.status == IN_PROGRESS:
                st = r.actual_start or st
                en = max(st + self._duration(r.exercise_type), now)
            states.append(SessionState(r.id, r.crew_id, r.exercise_type, r.day_index, r.ordinal, r.status,
                                       r.device_id, st, en, r.attempt, r.conflict))
        return {r.id: r for r in rows}, states

    def _clearances(self, s: Session, now: datetime) -> list[ClearanceView]:
        rows = s.scalars(select(MedicalClearance).where(MedicalClearance.revoked_at.is_(None),
                                                        MedicalClearance.valid_until >= now)).all()
        return [ClearanceView(r.id, r.crew_id, r.exercise_type, r.valid_from, r.valid_until, False, r.issued_by, r.created_at)
                for r in rows]

    def _label(self, crew_id: str, exercise_type: str) -> str:
        ex = self.cfg.exercise_types.get(exercise_type)
        return f"{crew_id} {ex.label if ex else exercise_type}"

    def _device_label(self, device_id: str | None) -> str:
        d = self.cfg.devices.get(device_id or "")
        return d.label if d else (device_id or "no device")

    # ------------------------------------------------------------ replan
    def replan(self, trigger: str) -> dict[str, Any]:
        core = self.core
        with core.lock, core.Session() as s:
            now = core.now()
            ctx = self._context(s, now)
            rows, states = self._sessions(s, now)
            outcomes = reconcile(ctx, states, trigger)
            result = self._apply(s, rows, outcomes, now, trigger)
            s.commit()
        self._last_replan = now
        return result

    def _apply(self, s: Session, rows: dict[str, ExerciseSession], outcomes: list[Outcome], now: datetime,
               trigger: str) -> dict[str, Any]:
        core = self.core
        counts: Counter[str] = Counter()
        out: list[dict[str, Any]] = []
        for o in outcomes:
            st = o.session
            row = rows.get(st.id)
            if row is None:
                row = ExerciseSession(id=st.id, crew_id=st.crew_id, exercise_type=st.exercise_type, day_index=st.day_index,
                                      ordinal=st.ordinal, status=st.status, attempt=0, plan_hash=self.plan.content_hash,
                                      created_at=now, updated_at=now)
                s.add(row)
            if row.status != IN_PROGRESS:
                if (row.planned_start, row.device_id) != (st.start, st.device_id) or st.status != row.status:
                    row.notified_at = None if st.status == PLANNED else row.notified_at
                row.planned_start, row.planned_end = st.start, st.end
            row.status, row.device_id, row.attempt, row.conflict = st.status, st.device_id, st.attempt, st.conflict
            row.plan_hash, row.updated_at = self.plan.content_hash, now
            for d in o.decisions:
                counts[d.action] += 1
                s.add(ScheduleDecision(
                    timestamp=now, session_id=d.session_id, crew_id=st.crew_id, exercise_type=st.exercise_type,
                    action=d.action, trigger=d.trigger[:40], reason=d.reason, conflict_code=d.conflict_code,
                    conflict_ref=d.conflict_ref, from_start=d.from_start, from_end=d.from_end, from_device=d.from_device,
                    to_start=d.to_start, to_end=d.to_end, to_device=d.to_device, plan_hash=self.plan.content_hash))
                payload = self._decision_dict(d, st.crew_id, st.exercise_type, now)
                core.enqueue(s, "CFMS_DECISION", payload)
                out.append(payload)
                if d.action != "CREATED":
                    core.log(LOG_CATEGORY, self._decision_text(d, st), "CFMS", s)
        if counts.get("CREATED"):
            core.log(LOG_CATEGORY, f"CFMS planning ({trigger}): {counts['CREATED']} session(s) placed, "
                                   f"{counts.get('UNSCHEDULABLE', 0)} without a valid window. Plan hash {self.plan.content_hash}.", "CFMS", s)
        return {"trigger": trigger, "changes": len(outcomes), "counts": dict(counts), "decisions": out}

    def _decision_text(self, d: Decision, st: SessionState) -> str:
        who = self._label(st.crew_id, st.exercise_type)
        frm = f"{self.met(d.from_start)} {d.from_device or ''}".strip() if d.from_start else "-"
        to = f"{self.met(d.to_start)} {d.to_device or ''}".strip() if d.to_start else "-"
        window = f" {frm} -> {to}." if d.from_start or d.to_start else ""
        return f"Planner {d.action.replace('_', ' ')}: {who} ({d.session_id}).{window} {d.reason}. Trigger: {d.trigger}."

    def _decision_dict(self, d: Decision, crew_id: str, exercise_type: str, ts: datetime, did: int | None = None) -> dict[str, Any]:
        return {
            "id": did, "timestamp": iso(ts), "session_id": d.session_id, "crew_id": crew_id, "exercise_type": exercise_type,
            "action": d.action, "trigger": d.trigger, "reason": d.reason, "conflict_code": d.conflict_code,
            "conflict_ref": d.conflict_ref, "from_start": iso(d.from_start), "from_start_met": self.met(d.from_start) if d.from_start else None,
            "from_end": iso(d.from_end), "from_device": d.from_device, "to_start": iso(d.to_start),
            "to_start_met": self.met(d.to_start) if d.to_start else None, "to_end": iso(d.to_end), "to_device": d.to_device,
            "plan_hash": self.plan.content_hash,
        }

    # -------------------------------------------------------------- tick
    def tick(self) -> None:
        now = self.core.now()
        if self._last_replan is None or (now - self._last_replan).total_seconds() >= self.cfg.policy.replan_interval_s:
            self.replan("TICK")
        self._notify()
        self._monitor_sessions()
        self._assess_recovery()
        self._tick_alarm_ctx()

    def _notify(self) -> None:
        core = self.core
        lead = timedelta(minutes=self.cfg.policy.notify_lead_min)
        with core.lock, core.Session() as s:
            now = core.now()
            due = s.scalars(select(ExerciseSession).where(ExerciseSession.status == PLANNED, ExerciseSession.notified_at.is_(None),
                                                          ExerciseSession.planned_start <= now + lead)
                            .order_by(ExerciseSession.planned_start, ExerciseSession.id)).all()
            if not due:
                return
            ctx = self._context(s, now)
            _, states = self._sessions(s, now)
            alerts, params, clear = core.list_alerts(), core.parameter_states(), self._clearances(s, now)
            latest = self._latest_recovery(s, now)
            for r in due:
                gate = self._gate(ctx, r, states, alerts, params, clear, latest=latest)
                r.status, r.notified_at, r.updated_at = NOTIFIED, now, now
                core.log(LOG_CATEGORY, f"Upcoming exercise: {self._label(r.crew_id, r.exercise_type)} at {self.met(r.planned_start)} "
                                       f"on {self._device_label(r.device_id)}. Safety gate: {gate['status'].replace('_', ' ')}.", "CFMS", s)
                core.enqueue(s, "CFMS_SESSION", {"session_id": r.id, "event": "NOTIFIED", "gate": gate["status"], "timestamp": iso(now)})
            s.commit()

    def _monitor_sessions(self) -> None:
        core = self.core
        with core.lock, core.Session() as s:
            rows = s.scalars(select(ExerciseSession).where(ExerciseSession.status == IN_PROGRESS)).all()
            if not rows:
                return
            now = core.now()
            params = core.parameter_states()
            alerts = core.list_alerts()
            cats = {p["id"]: p.get("category") for p in params}
            for r in rows:
                monitored = r.crew_id == self.monitored_crew_id
                profile = self.cfg.profiles.get(r.profile_id or "")
                ctx_data = dict(r.context or {})
                seen = list(ctx_data.get("alerts", []))
                if profile is not None:
                    ev = evaluate_profile(profile, params, monitored, self.cfg.hrmax(r.crew_id), self.profile_note())
                    hr = (ev.get("heart_rate") or {}).get("value")
                    if hr is not None:
                        r.peak_hr = hr if r.peak_hr is None else max(r.peak_hr, hr)
                    band = ev["overall"]
                    if self._profile_band.get(r.id) != band:
                        if r.id in self._profile_band or band != "IN_TARGET":
                            core.log(LOG_CATEGORY, f"Exercise profile {profile.id} ({r.id}): {ev['summary']}.", "CFMS", s)
                        self._profile_band[r.id] = band
                if monitored:
                    for a in alerts:
                        if a["id"] in seen or a["created_at"] is None or a["created_at"] < iso(r.actual_start):
                            continue
                        if cats.get(a.get("parameter") or "") not in ("physiological", None):
                            continue
                        seen.append(a["id"])
                        core.log(LOG_CATEGORY, f"Alert '{a['title']}' ({a['severity']}) raised during confirmed exercise session "
                                               f"{r.id}; alert NOT suppressed - exercise context recorded.", "CFMS", s)
                if seen != ctx_data.get("alerts", []):
                    ctx_data["alerts"] = seen
                    r.context = ctx_data
                r.updated_at = now
            s.commit()

    # ------------------------------------------------- exercise alarm context
    def _context_policy(self) -> bool:
        return self.cfg.exercise_alarm_policy == "context_hrmax"

    def profile_note(self) -> str:
        if self._context_policy():
            return ("DEMONSTRATION profile in % of the individual (SIMULATED) HRmax. During a confirmed session and its "
                    "recovery observation the high heart-rate alarm limits follow the exercise context (logged). Every "
                    "other alarm keeps its global limits and no alarm is suppressed.")
        return ("DEMONSTRATION profile for display and logging only. Global HEV-1 alert limits are unchanged and "
                "MASTER CAUTION / MASTER WARNING are never suppressed.")

    def alarm_thresholds(self, pdef):
        """Called by HevCore for every sample (in-memory, under core.lock)."""
        ctx = self._alarm_ctx
        if ctx is None or pdef.id != "heart_rate":
            return None
        return ctx["thresholds"]

    def alarm_context_label(self, pdef) -> str | None:
        ctx = self._alarm_ctx
        if ctx is None or pdef.id != "heart_rate":
            return None
        return (f"exercise context {ctx['session_id']} - {self.cfg.exercise_hr_alarm_pct['caution_high']:g}/"
                f"{self.cfg.exercise_hr_alarm_pct['warning_high']:g} % of SIMULATED HRmax {ctx['hrmax']:g} bpm")

    def _activate_alarm_ctx(self, r: ExerciseSession, s: Session, restored: bool = False, until: datetime | None = None) -> None:
        if not self._context_policy() or r.crew_id != self.monitored_crew_id or "heart_rate" not in self.core.reg.parameters:
            return
        hrmax = self.cfg.hrmax(r.crew_id)
        if not hrmax:
            return
        from dataclasses import replace as dc_replace
        base = self.core.reg.parameters["heart_rate"].thresholds
        pct = self.cfg.exercise_hr_alarm_pct
        th = dc_replace(base, advisory_high=None, caution_high=round(hrmax * pct["caution_high"] / 100.0),
                        warning_high=round(hrmax * pct["warning_high"] / 100.0))
        self._alarm_ctx = {"session_id": r.id, "crew_id": r.crew_id, "hrmax": hrmax, "until": until, "thresholds": th}
        g = base.as_dict()
        self.core.log(LOG_CATEGORY, f"Exercise alarm context {'RESTORED' if restored else 'ON'} ({r.id}): heart-rate alarm "
                                    f"limits caution > {th.caution_high:g} / warning > {th.warning_high:g} bpm "
                                    f"({pct['caution_high']:g}/{pct['warning_high']:g} % of SIMULATED HRmax {hrmax:g}). "
                                    f"Global {g.get('caution_high', '--')}/{g.get('warning_high', '--')} bpm resume after the "
                                    "recovery observation. Low-side HR limits and all other alarms unchanged.", "CFMS", s)
        self.core.enqueue(s, "CFMS_ALARM_CONTEXT", {"event": "ON", "session_id": r.id, "caution_high": th.caution_high,
                                                    "warning_high": th.warning_high, "timestamp": iso(self.core.now())})

    def _end_alarm_ctx(self, s: Session, reason: str) -> None:
        ctx = self._alarm_ctx
        if ctx is None:
            return
        self._alarm_ctx = None
        g = self.core.reg.parameters["heart_rate"].thresholds.as_dict()
        self.core.log(LOG_CATEGORY, f"Exercise alarm context OFF ({ctx['session_id']}): {reason}. Global heart-rate limits "
                                    f"{g.get('caution_high', '--')}/{g.get('warning_high', '--')} bpm restored.", "CFMS", s)
        self.core.enqueue(s, "CFMS_ALARM_CONTEXT", {"event": "OFF", "session_id": ctx["session_id"], "reason": reason,
                                                    "timestamp": iso(self.core.now())})

    def _tick_alarm_ctx(self) -> None:
        ctx = self._alarm_ctx
        if ctx is None or ctx["until"] is None:
            return
        core = self.core
        with core.lock, core.Session() as s:
            now = core.now()
            r = s.get(ExerciseSession, ctx["session_id"])
            rec = self._recovery(s, r, now) if r is not None else None
            if rec is not None and rec.get("final"):
                self._end_alarm_ctx(s, f"recovery {rec['status'].replace('_', ' ')}")
            elif now >= ctx["until"]:
                self._end_alarm_ctx(s, "recovery observation window ended")
            else:
                return
            s.commit()

    def _restore_alarm_ctx(self) -> None:
        core = self.core
        if not self._context_policy():
            return
        with core.lock, core.Session() as s:
            now = core.now()
            live = s.scalars(select(ExerciseSession).where(ExerciseSession.status == IN_PROGRESS,
                                                           ExerciseSession.crew_id == self.monitored_crew_id)).first()
            if live is not None:
                self._activate_alarm_ctx(live, s, restored=True)
            else:
                window = timedelta(minutes=self.cfg.recovery.window_min)
                last = s.scalars(select(ExerciseSession).where(ExerciseSession.status.in_(("COMPLETED", "ABORTED")),
                                                               ExerciseSession.crew_id == self.monitored_crew_id,
                                                               ExerciseSession.actual_end >= now - window)
                                 .order_by(desc(ExerciseSession.actual_end))).first()
                if last is not None and not ((last.context or {}).get("recovery") or {}).get("final"):
                    self._activate_alarm_ctx(last, s, restored=True, until=last.actual_end + window)
            s.commit()

    # ---------------------------------------------------------- recovery
    def _recovery_samples(self, s: Session, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        rows = s.execute(select(TelemetryRecord.timestamp, TelemetryRecord.value).where(
            TelemetryRecord.parameter == "heart_rate", TelemetryRecord.quality == "GOOD", TelemetryRecord.value.is_not(None),
            TelemetryRecord.timestamp >= start, TelemetryRecord.timestamp <= end).order_by(TelemetryRecord.timestamp)).all()
        return [(ts, float(v)) for ts, v in rows]

    def _recovery(self, s: Session, r: ExerciseSession, now: datetime,
                  samples: list[tuple[datetime, float]] | None = None) -> dict[str, Any] | None:
        """Stored final result, or a live evaluation. None for sessions that never ended."""
        if r.actual_end is None or r.status not in ("COMPLETED", "ABORTED"):
            return None
        stored = (r.context or {}).get("recovery")
        if stored and stored.get("final"):
            return stored
        c = self.cfg.recovery
        if samples is None:
            samples = self._recovery_samples(s, r.actual_end, r.actual_end + timedelta(minutes=c.window_min))
        stale = self.core.reg.parameters["heart_rate"].stale_after_s if "heart_rate" in self.core.reg.parameters else 10.0
        res = evaluate_recovery(monitored=r.crew_id == self.monitored_crew_id, pre_hr=r.pre_hr, end_hr=r.end_hr,
                                peak_hr=r.peak_hr, ended_at=r.actual_end, now=now, samples=samples,
                                stale_after_s=stale or 10.0, c=c)
        res["assessed_at"] = iso(now)
        return res

    def _latest_recovery(self, s: Session, now: datetime) -> dict[str, tuple[ExerciseSession, dict[str, Any]]]:
        since = now - timedelta(hours=self.cfg.recovery.validity_h)
        rows = s.scalars(select(ExerciseSession).where(ExerciseSession.status.in_(("COMPLETED", "ABORTED")),
                                                       ExerciseSession.actual_end >= since)
                         .order_by(desc(ExerciseSession.actual_end))).all()
        out: dict[str, tuple[ExerciseSession, dict[str, Any]]] = {}
        for r in rows:
            if r.crew_id not in out:
                res = self._recovery(s, r, now)
                if res is not None:
                    out[r.crew_id] = (r, res)
        return out

    def _assess_recovery(self) -> None:
        """Finalize recovery results once, log them and send them to the ground queue."""
        core = self.core
        with core.lock, core.Session() as s:
            now = core.now()
            since = now - timedelta(hours=self.cfg.recovery.validity_h)
            rows = s.scalars(select(ExerciseSession).where(ExerciseSession.status.in_(("COMPLETED", "ABORTED")),
                                                           ExerciseSession.actual_end >= since)).all()
            changed = False
            for r in rows:
                if ((r.context or {}).get("recovery") or {}).get("final"):
                    continue
                res = self._recovery(s, r, now)
                if res is None or not res["final"]:
                    continue
                ctx = dict(r.context or {})
                ctx["recovery"] = res
                r.context, r.updated_at = ctx, now
                effect = (" Next session of this crew member requires a Medical Clearance recorded after this finding."
                          if res["status"] in (REVIEW, DATA_INCOMPLETE) and r.crew_id == self.monitored_crew_id else "")
                core.log(LOG_CATEGORY, f"Recovery {res['status'].replace('_', ' ')}: {self._label(r.crew_id, r.exercise_type)} "
                                       f"({r.id}). {res['summary']}. DEMONSTRATION criteria.{effect}", "CFMS", s)
                core.enqueue(s, "CFMS_RECOVERY", {"session_id": r.id, "crew_id": r.crew_id, "status": res["status"],
                                                  "hrr60": res["hrr60"], "time_to_baseline_s": res["time_to_baseline_s"],
                                                  "summary": res["summary"], "timestamp": iso(now)})
                changed = True
            if changed:
                s.commit()

    def _recovery_gate(self, crew_id: str, start: datetime,
                       latest: dict[str, tuple[ExerciseSession, dict[str, Any]]]) -> tuple[list[dict[str, Any]], datetime | None]:
        """Extra gate reasons from the latest recovery result, and the earliest acceptable clearance time."""
        if crew_id != self.monitored_crew_id or crew_id not in latest:
            return [], None
        r, res = latest[crew_id]
        if r.actual_end is None or start > r.actual_end + timedelta(hours=self.cfg.recovery.validity_h) or start < r.actual_end:
            return [], None
        st = res["status"]
        if st == RECOVERING:
            return [{"level": "BLOCK", "code": "RECOVERY_IN_PROGRESS", "ref": r.id,
                     "text": f"Recovery from {r.id} still being observed ({res['summary']})"}], None
        if st in (REVIEW, DATA_INCOMPLETE):
            found = datetime.fromisoformat(res["assessed_at"].replace("Z", "+00:00")) if res.get("final") else r.actual_end
            code = "RECOVERY_REVIEW" if st == REVIEW else "RECOVERY_DATA_INCOMPLETE"
            return [{"level": "CLEARANCE", "code": code, "ref": r.id,
                     "text": f"Previous session {r.id}: recovery {st.replace('_', ' ')} - {res['summary']}. "
                             "Needs a Medical Clearance recorded after this finding"}], found
        return [], None

    def recovery_view(self, limit: int = 12) -> dict[str, Any]:
        core = self.core
        c = self.cfg.recovery
        with core.Session() as s:
            now = core.now()
            since = now - timedelta(hours=c.validity_h)
            rows = s.scalars(select(ExerciseSession).where(ExerciseSession.status.in_(("COMPLETED", "ABORTED")),
                                                           ExerciseSession.actual_end >= since)
                             .order_by(desc(ExerciseSession.actual_end)).limit(limit)).all()
            items = []
            for r in rows:
                samples = self._recovery_samples(s, r.actual_end, r.actual_end + timedelta(minutes=c.window_min))
                res = self._recovery(s, r, now, samples)
                curve, last_t = [], -999.0
                for ts, v in samples:
                    t = (ts - r.actual_end).total_seconds()
                    if t - last_t >= 4.5:
                        curve.append([round(t, 1), v])
                        last_t = t
                items.append({"session": self._ser(r), "recovery": res, "curve": curve})
            latest = self._latest_recovery(s, now)
        return {
            "criteria": {**c.__dict__, "provenance": "DEMONSTRATION"},
            "monitored_crew_id": self.monitored_crew_id,
            "latest_by_crew": [{"crew_id": cid, "session_id": latest[cid][0].id if cid in latest else None,
                                "recovery": latest[cid][1] if cid in latest else None} for cid in self.crew],
            "items": items,
        }

    def simulated_load_targets(self) -> dict[str, float]:
        """SIMULATED load for the simulator while the monitored crew member exercises."""
        with self.core.Session() as s:
            r = s.scalars(select(ExerciseSession).where(ExerciseSession.status == IN_PROGRESS,
                                                        ExerciseSession.crew_id == self.monitored_crew_id)).first()
            return dict(self.cfg.simulated_load.get(r.exercise_type, {})) if r else {}

    # -------------------------------------------------------------- gate
    def _gate(self, ctx: PlanningContext, r: ExerciseSession, states: list[SessionState], alerts: list[dict[str, Any]],
              params: list[dict[str, Any]], clearances: list[ClearanceView], start: datetime | None = None,
              latest: dict[str, tuple[ExerciseSession, dict[str, Any]]] | None = None) -> dict[str, Any]:
        st = start or r.planned_start
        if st is None:
            return {"status": BLOCKED, "reasons": [{"level": "BLOCK", "code": "NO_WINDOW", "ref": r.conflict,
                                                    "text": "No valid window in the Mission Plan"}],
                    "clearance": None, "evaluated_window": None, "disclaimer": GATE_DISCLAIMER}
        en = st + self._duration(r.exercise_type)
        occ = [x for x in states if x.status in OCCUPYING and x.id != r.id]
        pc = plan_conflict(ctx, r.crew_id, st, en, r.day_index) or crew_conflict(ctx, r.crew_id, st, en, occ, r.id)
        if pc is None:
            dc = device_conflict(ctx, r.device_id, st, en, occ, r.id)
            pc = dc if dc is not None and dc.code not in ("DEVICE_STATUS", "NO_DEVICE") else None
        if latest is None:
            with self.core.Session() as s2:
                latest = self._latest_recovery(s2, ctx.now)
        extra, found = self._recovery_gate(r.crew_id, st, latest)
        if found is not None:
            clearances = [c for c in clearances if c.issued_at is not None and c.issued_at >= found]
        return evaluate_gate(
            crew_id=r.crew_id, monitored_crew_id=self.monitored_crew_id, exercise_type=r.exercise_type, start=st, end=en,
            extra=extra,
            alerts=alerts, parameters=params, required_parameters=self.cfg.required_parameters,
            required_cabin_parameters=self.cfg.required_cabin_parameters, plan_conflict=pc,
            device_id=r.device_id, device_label=self._device_label(r.device_id),
            device_status=ctx.device_status.get(r.device_id or ""), clearances=clearances)

    # ---------------------------------------------------- session actions
    def _get(self, s: Session, sid: str) -> ExerciseSession:
        from app.services.core import NotFoundError
        row = s.get(ExerciseSession, sid)
        if row is None:
            raise NotFoundError(f"Exercise session {sid} not found")
        return row

    def start_session(self, sid: str) -> dict[str, Any]:
        core, pol = self.core, self.cfg.policy
        with core.lock, core.Session() as s:
            now = core.now()
            r = self._get(s, sid)
            if r.status not in MOVABLE:
                raise CfmsConflict(f"Session {sid} is {r.status}; only PLANNED or NOTIFIED sessions can start")
            if now < r.planned_start - timedelta(minutes=pol.start_early_min):
                raise CfmsConflict(f"Start window opens at {self.met(r.planned_start - timedelta(minutes=pol.start_early_min))}")
            if now > r.planned_start + timedelta(minutes=pol.start_grace_min):
                raise CfmsConflict("Start window has passed; the planner will reschedule this session")
            ctx = self._context(s, now)
            _, states = self._sessions(s, now)
            params = core.parameter_states()
            gate = self._gate(ctx, r, states, core.list_alerts(), params, self._clearances(s, now), start=now)
            if gate["status"] != READY:
                raise CfmsConflict(f"Safety gate: {gate['status'].replace('_', ' ')}", {"gate": gate})
            ex = self.cfg.exercise_types[r.exercise_type]
            monitored = r.crew_id == self.monitored_crew_id
            hr = next((p["value"] for p in params if p["id"] == "heart_rate" and p["status"] == "OK"), None) if monitored else None
            r.status, r.actual_start, r.gate_at_start, r.updated_at = IN_PROGRESS, now, gate, now
            r.clearance_id = (gate.get("clearance") or {}).get("id")
            r.profile_id, r.pre_hr, r.peak_hr = ex.profile_id, hr, hr
            r.context = {"alerts": [], "profile_id": ex.profile_id, "monitored": monitored}
            clear = f" under Medical Clearance {r.clearance_id[:8]}" if r.clearance_id else ""
            core.log(LOG_CATEGORY, f"Exercise session started: {self._label(r.crew_id, r.exercise_type)} on "
                                   f"{self._device_label(r.device_id)} - confirmed by crew. Safety gate READY PER PLAN{clear}. "
                                   f"DEMONSTRATION monitoring profile {ex.profile_id} applied (% of SIMULATED HRmax; "
                                   "no alarm suppressed).", "CFMS", s)
            self._activate_alarm_ctx(r, s)
            core.enqueue(s, "CFMS_SESSION", {"session_id": sid, "event": "STARTED", "profile_id": ex.profile_id,
                                             "clearance_id": r.clearance_id, "timestamp": iso(now)})
            s.commit()
            return self._ser(r)

    def _finish(self, sid: str, status: str, reason: str) -> dict[str, Any]:
        core = self.core
        with core.lock, core.Session() as s:
            now = core.now()
            r = self._get(s, sid)
            if r.status != IN_PROGRESS:
                raise CfmsConflict(f"Session {sid} is {r.status}; only an IN_PROGRESS session can be ended")
            hr = None
            if r.crew_id == self.monitored_crew_id:
                hr = next((p["value"] for p in core.parameter_states() if p["id"] == "heart_rate" and p["status"] == "OK"), None)
            r.status, r.actual_end, r.end_hr, r.end_reason, r.updated_at = status, now, hr, reason, now
            mins = (now - r.actual_start).total_seconds() / 60 if r.actual_start else 0
            core.log(LOG_CATEGORY, f"Exercise session {status.lower()}: {self._label(r.crew_id, r.exercise_type)} "
                                   f"({sid}) after {mins:.0f} min. {reason}".strip(), "CFMS", s)
            core.enqueue(s, "CFMS_SESSION", {"session_id": sid, "event": status, "reason": reason, "timestamp": iso(now)})
            if self._alarm_ctx is not None and self._alarm_ctx["session_id"] == sid:
                self._alarm_ctx["until"] = now + timedelta(minutes=self.cfg.recovery.window_min)
            s.commit()
            self._profile_band.pop(sid, None)
            return self._ser(r)

    def complete_session(self, sid: str) -> dict[str, Any]:
        return self._finish(sid, "COMPLETED", "")

    def abort_session(self, sid: str, reason: str) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("An abort reason is required")
        return self._finish(sid, "ABORTED", f"Reason: {reason.strip()}")

    def request_earliest(self, sid: str) -> dict[str, Any]:
        core = self.core
        with core.lock, core.Session() as s:
            now = core.now()
            self._get(s, sid)
            ctx = self._context(s, now)
            rows, states = self._sessions(s, now)
            if sid not in rows:
                raise CfmsConflict(f"Session {sid} is outside the active planning window")
            outcome, conflict = reschedule_earliest(ctx, states, sid)
            if outcome is None:
                raise CfmsConflict(conflict.text if conflict else "No earlier valid window")
            result = self._apply(s, rows, [outcome], now, "CREW_REQUEST")
            s.commit()
            return {"session": self._ser(rows[sid]), "decision": result["decisions"][0]}

    # ------------------------------------------------- plan / equipment
    def add_activity(self, *, activity_type: str, title: str, crew: list[str], start: datetime, duration_min: int,
                     device_id: str | None = None, source: str = "MANUAL", note: str = "") -> dict[str, Any]:
        core = self.core
        if activity_type not in self.cfg.activity_rules:
            raise ValueError(f"Unknown activity type {activity_type}. Valid: {', '.join(self.cfg.activity_rules)}")
        crew = list(crew or [ALL])
        if any(c != ALL and c not in self.crew for c in crew) or (ALL in crew and len(crew) > 1):
            raise ValueError("crew must be [ALL] or a list of known crew member ids")
        if device_id is not None and device_id not in self.cfg.devices:
            raise ValueError(f"Unknown device {device_id}")
        if source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)}")
        if not 1 <= duration_min <= 1440:
            raise ValueError("duration_min must be within 1-1440")
        if not title.strip():
            raise ValueError("title is required")
        with core.lock, core.Session() as s:
            now = core.now()
            end = start + timedelta(minutes=duration_min)
            if end <= now:
                raise ValueError("The activity ends in the past")
            n = len(s.scalars(select(RuntimeActivity.id)).all()) + 1
            aid = f"RT-{n:04d}"
            s.add(RuntimeActivity(id=aid, activity_type=activity_type, title=title.strip(), crew=crew, start=start, end=end,
                                  device_id=device_id, source=source, status="ACTIVE", note=note, created_at=now))
            core.log(LOG_CATEGORY, f"Unplanned activity {aid} added: {activity_type} '{title.strip()}' {self.met(start)} - "
                                   f"{self.met(end)} for {', '.join(crew)} (source {source}). Baseline plan unchanged.", "CFMS", s)
            core.enqueue(s, "CFMS_ACTIVITY", {"id": aid, "event": "ADDED", "type": activity_type, "start": iso(start),
                                              "end": iso(end), "crew": crew, "source": source, "timestamp": iso(now)})
            s.commit()
        return {"activity": self.get_activity(aid), "replan": self.replan(f"PLAN_CHANGE {aid}")}

    def cancel_activity(self, aid: str) -> dict[str, Any]:
        from app.services.core import NotFoundError
        core = self.core
        if aid in self.plan.baseline_ids() or not aid.upper().startswith("RT-"):
            raise CfmsConflict("Baseline activities come only from config/mission_plan.yaml and cannot be changed at runtime")
        with core.lock, core.Session() as s:
            row = s.get(RuntimeActivity, aid)
            if row is None:
                raise NotFoundError(f"Runtime activity {aid} not found")
            if row.status != "ACTIVE":
                raise CfmsConflict(f"Runtime activity {aid} is {row.status}")
            now = core.now()
            row.status, row.cancelled_at = "CANCELLED", now
            core.log(LOG_CATEGORY, f"Unplanned activity {aid} cancelled ({row.activity_type} '{row.title}').", "CFMS", s)
            core.enqueue(s, "CFMS_ACTIVITY", {"id": aid, "event": "CANCELLED", "timestamp": iso(now)})
            s.commit()
        return {"activity": self.get_activity(aid), "replan": self.replan(f"PLAN_CHANGE {aid}")}

    def get_activity(self, aid: str) -> dict[str, Any]:
        with self.core.Session() as s:
            r = s.get(RuntimeActivity, aid)
            return self._ser_runtime(r)

    def set_equipment(self, device_id: str, status: str, note: str = "", source: str = "MANUAL") -> dict[str, Any]:
        core = self.core
        if device_id not in self.cfg.devices:
            from app.services.core import NotFoundError
            raise NotFoundError(f"Device {device_id} not found")
        if status not in DEVICE_STATUSES:
            raise ValueError(f"status must be one of {', '.join(DEVICE_STATUSES)}")
        if source not in SOURCES:
            raise ValueError(f"source must be one of {', '.join(SOURCES)}")
        with core.lock, core.Session() as s:
            now = core.now()
            old = self._device_status(s)[device_id]
            if old == status:
                return {"device": self._equipment(s)[device_id], "replan": None}
            row = s.get(EquipmentState, device_id)
            if row is None:
                s.add(EquipmentState(device_id=device_id, status=status, note=note, source=source, updated_at=now))
            else:
                row.status, row.note, row.source, row.updated_at = status, note, source, now
            core.log(LOG_CATEGORY, f"Equipment {device_id} ({self._device_label(device_id)}): {old} -> {status}"
                                   + (f". {note}" if note else "") + f" (source {source}).", "CFMS", s)
            core.enqueue(s, "CFMS_EQUIPMENT", {"device_id": device_id, "from": old, "to": status, "note": note, "timestamp": iso(now)})
            s.commit()
        replan = self.replan(f"DEVICE_CHANGE {device_id}")
        with core.Session() as s:
            return {"device": self._equipment(s)[device_id], "replan": replan}

    def _equipment(self, s: Session) -> dict[str, dict[str, Any]]:
        status = self._device_status(s)
        rows = {r.device_id: r for r in s.scalars(select(EquipmentState)).all()}
        out = {}
        for d in self.cfg.devices.values():
            r = rows.get(d.id)
            out[d.id] = {"id": d.id, "label": d.label, "class": d.device_class, "status": status[d.id],
                         "note": r.note if r else "", "updated_at": iso(r.updated_at) if r else None, "provenance": "SIMULATED"}
        return out

    # ------------------------------------------------------ clearances
    def grant_clearance(self, *, crew_id: str, exercise_type: str, valid_until: datetime, issued_by: str,
                        valid_from: datetime | None = None, note: str = "") -> dict[str, Any]:
        core = self.core
        if crew_id not in self.crew:
            raise ValueError(f"Unknown crew member {crew_id}")
        if exercise_type not in self.cfg.exercise_types:
            raise ValueError(f"Unknown exercise type {exercise_type}")
        if not issued_by.strip():
            raise ValueError("issued_by is required")
        with core.lock, core.Session() as s:
            now = core.now()
            vf = valid_from or now
            if vf < now - timedelta(minutes=5):
                raise ValueError("valid_from cannot be in the past")
            if valid_until <= vf or valid_until <= now:
                raise ValueError("valid_until must be after valid_from and in the future")
            if valid_until - vf > timedelta(hours=self.cfg.clearance_max_validity_h):
                raise ValueError(f"A Medical Clearance is limited to {self.cfg.clearance_max_validity_h:g} h")
            cid = new_id()
            s.add(MedicalClearance(id=cid, crew_id=crew_id, exercise_type=exercise_type, valid_from=vf, valid_until=valid_until,
                                   issued_by=issued_by.strip(), note=note, created_at=now))
            core.log(LOG_CATEGORY, f"Medical Clearance {cid[:8]} recorded for {crew_id} {exercise_type}, valid {self.met(vf)} - "
                                   f"{self.met(valid_until)}, by {issued_by.strip()} (SIMULATED record). "
                                   "It cannot override blockers.", "CFMS", s)
            core.enqueue(s, "CFMS_CLEARANCE", {"id": cid, "event": "GRANTED", "crew_id": crew_id, "exercise_type": exercise_type,
                                               "valid_from": iso(vf), "valid_until": iso(valid_until), "timestamp": iso(now)})
            s.commit()
            return self._ser_clearance(s.get(MedicalClearance, cid), now)

    def revoke_clearance(self, cid: str, reason: str) -> dict[str, Any]:
        from app.services.core import NotFoundError
        core = self.core
        with core.lock, core.Session() as s:
            r = s.get(MedicalClearance, cid)
            if r is None:
                raise NotFoundError(f"Medical Clearance {cid} not found")
            if r.revoked_at is not None:
                raise CfmsConflict("Medical Clearance already revoked")
            now = core.now()
            r.revoked_at, r.revoked_reason = now, reason.strip() or "Revoked"
            core.log(LOG_CATEGORY, f"Medical Clearance {cid[:8]} for {r.crew_id} {r.exercise_type} revoked. {r.revoked_reason}", "CFMS", s)
            core.enqueue(s, "CFMS_CLEARANCE", {"id": cid, "event": "REVOKED", "reason": r.revoked_reason, "timestamp": iso(now)})
            s.commit()
            return self._ser_clearance(r, now)

    def clearances(self, include_inactive: bool = False) -> list[dict[str, Any]]:
        with self.core.Session() as s:
            now = self.core.now()
            q = select(MedicalClearance).order_by(desc(MedicalClearance.created_at))
            rows = s.scalars(q).all()
            out = [self._ser_clearance(r, now) for r in rows]
        return out if include_inactive else [c for c in out if c["active"]]

    def _ser_clearance(self, r: MedicalClearance, now: datetime) -> dict[str, Any]:
        active = r.revoked_at is None and r.valid_from <= now <= r.valid_until
        state = "REVOKED" if r.revoked_at else ("EXPIRED" if now > r.valid_until else ("ACTIVE" if active else "PENDING"))
        return {"id": r.id, "crew_id": r.crew_id, "exercise_type": r.exercise_type, "valid_from": iso(r.valid_from),
                "valid_until": iso(r.valid_until), "valid_from_met": self.met(r.valid_from), "valid_until_met": self.met(r.valid_until),
                "issued_by": r.issued_by, "note": r.note, "created_at": iso(r.created_at), "revoked_at": iso(r.revoked_at),
                "revoked_reason": r.revoked_reason, "state": state, "active": active or state == "PENDING",
                "provenance": "SIMULATED clearance record (prototype). Scoped to one crew member, one exercise type and a validity period."}

    # ---------------------------------------------------------- queries
    def _ser(self, r: ExerciseSession, gate: dict[str, Any] | None = None) -> dict[str, Any]:
        ex = self.cfg.exercise_types.get(r.exercise_type)
        return {
            "id": r.id, "crew_id": r.crew_id, "exercise_type": r.exercise_type, "exercise_label": ex.label if ex else r.exercise_type,
            "day_index": r.day_index, "ordinal": r.ordinal, "status": r.status, "device_id": r.device_id,
            "device_label": self._device_label(r.device_id) if r.device_id else None, "duration_min": ex.duration_min if ex else None,
            "planned_start": iso(r.planned_start), "planned_end": iso(r.planned_end),
            "planned_start_met": self.met(r.planned_start) if r.planned_start else None,
            "planned_end_met": self.met(r.planned_end) if r.planned_end else None,
            "attempt": r.attempt, "conflict": r.conflict, "notified_at": iso(r.notified_at),
            "actual_start": iso(r.actual_start), "actual_end": iso(r.actual_end), "clearance_id": r.clearance_id,
            "profile_id": r.profile_id, "pre_hr": r.pre_hr, "peak_hr": r.peak_hr, "end_hr": r.end_hr, "end_reason": r.end_reason,
            "monitored": r.crew_id == self.monitored_crew_id, "gate": gate, "provenance": "SIMULATED",
        }

    def _ser_runtime(self, r: RuntimeActivity) -> dict[str, Any]:
        return {"id": r.id, "type": r.activity_type, "title": r.title, "crew": list(r.crew), "start": iso(r.start), "end": iso(r.end),
                "start_met": self.met(r.start), "end_met": self.met(r.end), "device_id": r.device_id, "source": r.source,
                "status": r.status, "note": r.note, "origin": "RUNTIME", "editable": r.status == "ACTIVE"}

    def schedule(self, crew_id: str | None = None, state: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        core = self.core
        alerts = (state or {}).get("alerts") if state else None
        params = (state or {}).get("parameters") if state else None
        alerts = core.list_alerts() if alerts is None else alerts
        params = core.parameter_states() if params is None else params
        with core.Session() as s:
            now = core.now()
            ctx = self._context(s, now)
            rows, states = self._sessions(s, now)
            clear = self._clearances(s, now)
            today = day_of(self.met_start, now)
            sel = [r for r in rows.values() if r.day_index >= today and (crew_id is None or r.crew_id == crew_id)]
            sel.sort(key=lambda r: (r.day_index, r.planned_start is None, r.planned_start or now, r.id))
            latest = self._latest_recovery(s, now)
            out = []
            for r in sel:
                gate = self._gate(ctx, r, states, alerts, params, clear, latest=latest) if r.status in (PLANNED, NOTIFIED) else None
                out.append(self._ser(r, gate))
            return out

    def plan_view(self) -> dict[str, Any]:
        with self.core.Session() as s:
            now = self.core.now()
            ctx = self._context(s, now)
            lo, hi = now - timedelta(hours=6), now + timedelta(hours=self.cfg.policy.horizon_h)
            acts = [a for a in ctx.activities if a.end > lo and a.start < hi]
            runtime = {r.id: r for r in s.scalars(select(RuntimeActivity)).all()}
        items = []
        for a in acts:
            rule = self.cfg.activity_rules.get(a.type)
            items.append({"id": a.id, "type": a.type, "title": a.title, "crew": list(a.crew), "start": iso(a.start), "end": iso(a.end),
                          "start_met": self.met(a.start), "end_met": self.met(a.end), "device_id": a.device_id,
                          "origin": "BASELINE" if a.source == "BASELINE" else "RUNTIME", "source": a.source,
                          "scope": rule.scope if rule else "crew", "buffer_before_min": rule.before_min if rule else 0,
                          "buffer_after_min": rule.after_min if rule else 0,
                          "editable": a.source != "BASELINE" and a.id in runtime and runtime[a.id].status == "ACTIVE"})
        phases = [{"id": p.id, "type": p.type, "title": p.title, "start": iso(p.start), "end": iso(p.end),
                   "start_met": self.met(p.start), "end_met": self.met(p.end),
                   "exercise_allowed": p.type not in self.cfg.forbidden_phase_types} for p in ctx.phases
                  if p.end > lo and p.start < hi]
        return {"plan_id": self.plan.plan_id, "revision": self.plan.revision, "content_hash": self.plan.content_hash,
                "provenance": self.plan.provenance, "source_of_truth": "config/mission_plan.yaml (baseline) + SQLite runtime additions",
                "horizon_h": self.cfg.policy.horizon_h, "now_met": self.met(now), "phase_now": self._phase_now(ctx),
                "phases": phases, "activities": items}

    def _phase_now(self, ctx: PlanningContext) -> dict[str, Any] | None:
        p = next((p for p in ctx.phases if p.start <= ctx.now < p.end), None)
        return {"id": p.id, "type": p.type, "title": p.title, "exercise_allowed": p.type not in self.cfg.forbidden_phase_types} if p else None

    def decisions(self, session_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with self.core.Session() as s:
            q = select(ScheduleDecision)
            if session_id:
                q = q.where(ScheduleDecision.session_id == session_id)
            rows = s.scalars(q.order_by(desc(ScheduleDecision.id)).limit(limit)).all()
            return [self._decision_dict(Decision(r.session_id, r.action, r.trigger, r.reason, r.conflict_code, r.conflict_ref,
                                                 r.from_start, r.from_end, r.from_device, r.to_start, r.to_end, r.to_device),
                                        r.crew_id, r.exercise_type, r.timestamp, r.id) | {"plan_hash": r.plan_hash} for r in rows]

    def session_detail(self, sid: str) -> dict[str, Any]:
        core = self.core
        with core.Session() as s:
            now = core.now()
            r = self._get(s, sid)
            gate = None
            if r.status in (PLANNED, NOTIFIED):
                ctx = self._context(s, now)
                _, states = self._sessions(s, now)
                gate = self._gate(ctx, r, states, core.list_alerts(), core.parameter_states(), self._clearances(s, now))
            data = self._ser(r, gate)
            data["gate_at_start"] = r.gate_at_start
            data["context"] = r.context
        data["decisions"] = self.decisions(sid, 200)
        return data

    def equipment(self) -> list[dict[str, Any]]:
        with self.core.Session() as s:
            return list(self._equipment(s).values())

    def summary(self, state: dict[str, Any]) -> dict[str, Any]:
        """Compact block for GET /api/state."""
        core = self.core
        alerts, params = state.get("alerts", []), state.get("parameters", [])
        with core.Session() as s:
            now = core.now()
            ctx = self._context(s, now)
            rows, states = self._sessions(s, now)
            clear = self._clearances(s, now)
            today = day_of(self.met_start, now)
            live = [r for r in rows.values() if r.day_index >= today or r.status == IN_PROGRESS]
            latest = self._latest_recovery(s, now)
            next_by_crew = []
            for cid in self.crew:
                cands = [r for r in live if r.crew_id == cid and r.status in (IN_PROGRESS, NOTIFIED, PLANNED)]
                cands.sort(key=lambda r: (r.status != IN_PROGRESS, r.planned_start or now, r.id))
                r = cands[0] if cands else None
                item = None
                if r is not None:
                    item = self._ser(r, self._gate(ctx, r, states, alerts, params, clear, latest=latest)
                                     if r.status != IN_PROGRESS else None)
                next_by_crew.append({"crew_id": cid, "monitored": cid == self.monitored_crew_id, "session": item})
            in_progress = []
            alert_context: dict[str, str] = {}
            for r in (x for x in live if x.status == IN_PROGRESS):
                profile = self.cfg.profiles.get(r.profile_id or "")
                item = self._ser(r)
                item["profile"] = (evaluate_profile(profile, params, r.crew_id == self.monitored_crew_id, self.cfg.hrmax(r.crew_id),
                                                    self.profile_note()) if profile else None)
                in_progress.append(item)
                for aid in (r.context or {}).get("alerts", []):
                    alert_context[aid] = r.id
            horizon_rows = [r for r in live if r.day_index >= today]
            counts = Counter(r.status for r in horizon_rows)
            unscheduled = [self._ser(r) for r in sorted(horizon_rows, key=lambda r: r.id) if r.status == UNSCHEDULED]
            notes = s.scalars(select(MissionLogEntry).where(MissionLogEntry.category == LOG_CATEGORY)
                              .order_by(desc(MissionLogEntry.id)).limit(6)).all()
            last = s.scalars(select(ScheduleDecision).order_by(desc(ScheduleDecision.id)).limit(1)).first()
            return {
                "enabled": True,
                "provenance": self.cfg.provenance,
                "plan": {"plan_id": self.plan.plan_id, "revision": self.plan.revision, "content_hash": self.plan.content_hash,
                         "provenance": self.plan.provenance, "phase_now": self._phase_now(ctx), "now_met": self.met(now),
                         "horizon_h": self.cfg.policy.horizon_h},
                "next_by_crew": next_by_crew,
                "in_progress": in_progress,
                "unscheduled": unscheduled,
                "counts": dict(counts),
                "equipment": list(self._equipment(s).values()),
                "active_clearances": [self._ser_clearance(c, now) for c in
                                      s.scalars(select(MedicalClearance).where(MedicalClearance.revoked_at.is_(None),
                                                                               MedicalClearance.valid_until >= now)).all()],
                "notifications": [{"id": n.id, "timestamp": iso(n.timestamp), "message": n.message} for n in notes],
                "alert_context": alert_context,
                "alarm_policy": self.cfg.exercise_alarm_policy,
                "alarm_context": ({"session_id": self._alarm_ctx["session_id"], "crew_id": self._alarm_ctx["crew_id"],
                                   "hrmax_bpm": self._alarm_ctx["hrmax"], "caution_high": self._alarm_ctx["thresholds"].caution_high,
                                   "warning_high": self._alarm_ctx["thresholds"].warning_high,
                                   "until": iso(self._alarm_ctx["until"])} if self._alarm_ctx else None),
                "recovery": [{"crew_id": cid, "session_id": latest[cid][0].id, "exercise_type": latest[cid][0].exercise_type,
                              **{k: latest[cid][1].get(k) for k in ("status", "final", "summary", "hrr60", "time_to_baseline_s",
                                                                    "elapsed_s", "window_s")}}
                             for cid in self.crew if cid in latest],
                "last_decision_id": last.id if last else 0,
            }
