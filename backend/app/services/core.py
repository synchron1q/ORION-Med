# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""HEV-1 core: telemetry ingestion, alert management, stale detection, R.I.D.G.E.

All state-changing operations go through this class under one lock so the
simulator, the background monitor and API requests see a consistent state.
The simulator uses exactly the same `ingest` path as real sensors.
"""
from __future__ import annotations

import math
import statistics
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.core.registry import ParameterDef, Registry, load_registry
from app.core.settings import APP_VERSION, Settings
from app.database import init_db, make_engine, make_session_factory
from app.engine import alert_machine as am
from app.engine.correlation import UNCERTAINTY, Observation, evaluate_rules
from app.engine.readiness import evaluate_eva_readiness, evaluate_triage_focus
from app.engine.rules import Severity, classify, evaluate
from app.models import (
    AlertEvent,
    AlertHistory,
    CountermeasureExecution,
    CrewMember,
    Mission,
    MissionConfiguration,
    MissionLogEntry,
    NasaWeatherCache,
    PsychologicalAssessment,
    PVTResult,
    RadiationEvent,
    SyncQueueItem,
    TelemetryRecord,
    new_id,
)

SOURCES = ("SENSOR", "SIMULATED", "CREW_INPUT", "IMPORTED")
QUALITIES = ("GOOD", "SUSPECT", "FAULT")
RIDGE_RECOVERY_HOLD_S = 10.0
SENSOR_PROTOCOL = "CM-SENSOR-01"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if dt else None


def fmt(v: float | None) -> str:
    if v is None:
        return "--"
    return f"{v:.1f}" if abs(v) < 100 else f"{v:.0f}"


class IngestError(ValueError):
    pass


class NotFoundError(LookupError):
    pass


@dataclass
class TelemetryInput:
    parameter: str
    value: float | None
    unit: str | None = None
    timestamp: datetime | None = None
    source: str = "SENSOR"
    quality: str = "GOOD"
    crew_id: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class ParamState:
    value: float | None = None
    timestamp: datetime | None = None
    source: str | None = None
    quality: str | None = None
    last_valid_value: float | None = None
    last_valid_ts: datetime | None = None
    last_valid_source: str | None = None
    fault: bool = False
    fault_reason: str | None = None
    trend: deque = field(default_factory=lambda: deque(maxlen=90))
    observations: deque = field(default_factory=lambda: deque(maxlen=1200))


class HevCore:
    def __init__(self, settings: Settings, now_fn: Callable[[], datetime] = utcnow, registry: Registry | None = None):
        self.settings = settings
        self.now = now_fn
        self.reg = registry or load_registry(settings.config_dir)
        self.engine = make_engine(settings.database_path)
        init_db(self.engine)
        self.Session = make_session_factory(self.engine)
        self.lock = threading.RLock()
        self.started_at = self.now()
        self.state: dict[str, ParamState] = {pid: ParamState() for pid in self.reg.parameters}
        self.mission_id, self.crew_id = self._bootstrap()
        self._restore_state()

        from app.integrations.osdr import OsdrService
        from app.services.simulator import Simulator
        from app.services.sync import SyncManager

        self.simulator = Simulator(self)
        self.sync = SyncManager(self)
        self.osdr = OsdrService(self)
        self.ksp_telemetry: dict[str, Any] = {}
        self.ksp_last_seen: datetime | None = None
        self.ksp_current_phase: str = "NOMINAL_PAD"
        self.ksp_acked_phase: str | None = None
        self.ksp_was_in_space: bool = False
        self.ksp_prev_alt: float | None = None
        self.fitness = None  # optional CFMS module, only with ORION_CFMS_ENABLED=true
        if settings.cfms_enabled:
            from app.cfms.service import FitnessService

            self.fitness = FitnessService(self)
        self.log("SYSTEM", f"HEV-1 core v{APP_VERSION} started; local database ready")

    # ------------------------------------------------------------------ setup
    def _bootstrap(self) -> tuple[str, str | None]:
        m = self.reg.mission
        mid = m.get("id", "MISSION")
        with self.Session() as s:
            mission = s.get(Mission, mid)
            if mission is None:
                now = self.now()
                mission = Mission(
                    id=mid,
                    name=m.get("name", mid),
                    environment=m.get("environment", "UNSPECIFIED"),
                    vehicle=m.get("vehicle", "UNSPECIFIED"),
                    met_start_utc=now - timedelta(hours=float(m.get("initial_met_hours", 0))),
                    created_at=now,
                )
                s.add(mission)
                s.flush()
                for c in self.reg.crew:
                    s.add(CrewMember(id=c["id"], mission_id=mid, name=c["name"], role=c["role"], monitored=bool(c.get("monitored"))))
                s.commit()
            monitored = s.scalars(select(CrewMember).where(CrewMember.mission_id == mid, CrewMember.monitored.is_(True))).first()
            return mid, monitored.id if monitored else None

    def _restore_state(self) -> None:
        """Rebuild the in-memory latest-value cache from SQLite after a restart."""
        horizon = self.now() - timedelta(hours=1)
        with self.Session() as s:
            for pid, st in self.state.items():
                last = s.scalars(select(TelemetryRecord).where(TelemetryRecord.parameter == pid).order_by(desc(TelemetryRecord.timestamp)).limit(1)).first()
                if last is None:
                    continue
                st.value, st.timestamp, st.source, st.quality = last.value, last.timestamp, last.source, last.quality
                valid = s.scalars(
                    select(TelemetryRecord)
                    .where(TelemetryRecord.parameter == pid, TelemetryRecord.quality == "GOOD")
                    .order_by(desc(TelemetryRecord.timestamp))
                    .limit(1200)
                ).all()
                if valid:
                    st.last_valid_value, st.last_valid_ts, st.last_valid_source = valid[0].value, valid[0].timestamp, valid[0].source
                    pdef = self.reg.parameters[pid]
                    for r in reversed(valid):
                        if r.timestamp >= horizon:
                            st.observations.append(Observation(r.value, classify(r.value, pdef.thresholds), r.timestamp))
                    for r in reversed(valid[:90]):
                        st.trend.append((r.timestamp, r.value))
                st.fault = last.quality in ("FAULT", "INVALID")

    # --------------------------------------------------------------- runtime
    def get_runtime(self, key: str, default: Any = None) -> Any:
        with self.Session() as s:
            row = s.get(MissionConfiguration, key)
            return row.value if row else default

    def set_runtime(self, key: str, value: Any, s: Session | None = None) -> None:
        own = s is None
        s = s or self.Session()
        try:
            row = s.get(MissionConfiguration, key)
            if row is None:
                s.add(MissionConfiguration(key=key, mission_id=self.mission_id, value=value, updated_at=self.now()))
            else:
                row.value = value
                row.updated_at = self.now()
            if own:
                s.commit()
        finally:
            if own:
                s.close()

    def enqueue(self, s: Session, event_type: str, payload: dict[str, Any]) -> None:
        s.add(SyncQueueItem(item_id=new_id(), event_type=event_type, payload=payload, created_at=self.now(), status="PENDING"))

    def log(self, category: str, message: str, source: str = "SYSTEM", s: Session | None = None) -> None:
        own = s is None
        s = s or self.Session()
        try:
            now = self.now()
            s.add(MissionLogEntry(timestamp=now, category=category, message=message, source=source))
            self.enqueue(s, "MISSION_LOG", {"category": category, "message": message, "source": source, "timestamp": iso(now)})
            if own:
                s.commit()
        finally:
            if own:
                s.close()

    # ---------------------------------------------------------------- alerts
    def _open_alert(self, s: Session, rule_id: str) -> AlertEvent | None:
        return s.scalars(
            select(AlertEvent).where(AlertEvent.rule_id == rule_id, AlertEvent.lifecycle != am.CLEARED).order_by(desc(AlertEvent.created_at))
        ).first()

    def _record(self, s: Session, alert: AlertEvent, transitions: list[am.Transition], ts: datetime) -> None:
        for t in transitions:
            s.add(AlertHistory(alert_id=alert.id, timestamp=ts, event_type=t.event_type, detail=t.detail, actor=t.actor, severity=alert.severity, lifecycle=alert.lifecycle))
            self.enqueue(s, f"ALERT_{t.event_type}", {
                "alert_id": alert.id, "rule_id": alert.rule_id, "title": alert.title,
                "severity": Severity(alert.severity).name, "lifecycle": alert.lifecycle,
                "detail": t.detail, "actor": t.actor, "data_source": alert.data_source, "timestamp": iso(ts),
            })

    def _raise(self, s: Session, *, rule_id: str, kind: str, parameter: str | None, zone: str, title: str, message: str,
               data_source: str, protocol_id: str | None, severity: Severity, unit: str | None, value: float | None,
               ts: datetime, factors: list | None = None) -> AlertEvent:
        prior = s.scalar(select(func.count()).select_from(AlertEvent).where(AlertEvent.rule_id == rule_id)) or 0
        alert = AlertEvent(
            id=new_id(), mission_id=self.mission_id, crew_id=self.crew_id, rule_id=rule_id, kind=kind,
            parameter=parameter, zone=zone, title=title, message=message, data_source=data_source,
            protocol_id=protocol_id, unit=unit, trigger_value=value, last_value=value, factors=factors,
            created_at=ts, updated_at=ts, severity=int(severity), peak_severity=int(severity),
            lifecycle=am.ACTIVE, cm_status=am.CM_NONE, cm_steps_done=[], occurrence_count=1,
        )
        transitions = am.init_alert(alert, severity, ts, has_protocol=protocol_id is not None)
        if prior:
            transitions[0].detail += f" (repeat #{prior + 1} of {rule_id})"
        s.add(alert)
        s.flush()
        self._record(s, alert, transitions, ts)
        return alert

    @staticmethod
    def _direction(pdef: ParameterDef, value: float) -> str:
        th = pdef.thresholds
        lows = [v for v in (th.advisory_low, th.caution_low, th.warning_low) if v is not None]
        return "low" if lows and value <= max(lows) + th.hysteresis else "high"

    def effective_thresholds(self, pdef: ParameterDef):
        """Global limits, or the logged exercise-context limits provided by CFMS (heart rate only)."""
        fitness = getattr(self, "fitness", None)
        if fitness is not None:
            ctx = fitness.alarm_thresholds(pdef)
            if ctx is not None:
                return ctx
        return pdef.thresholds

    def limits_context(self, pdef: ParameterDef) -> str | None:
        fitness = getattr(self, "fitness", None)
        return fitness.alarm_context_label(pdef) if fitness is not None else None

    def _threshold_text(self, pdef: ParameterDef, value: float, sev: Severity) -> tuple[str, str]:
        direction = self._direction(pdef, value)
        limit = getattr(self.effective_thresholds(pdef), f"{sev.name.lower()}_{direction}", None)
        unit = pdef.unit
        title = f"{pdef.label.upper()} {'HIGH' if direction == 'high' else 'LOW'}"
        where = "above" if direction == "high" else "below"
        msg = f"{pdef.label} is {fmt(value)} {unit}, {where} the configured {sev.name.lower()} limit"
        msg += f" of {fmt(limit)} {unit} (demonstration threshold)." if limit is not None else " (demonstration threshold)."
        ctx = self.limits_context(pdef)
        if ctx:
            msg += f" Limit context: {ctx}."
        return title, msg

    # --------------------------------------------------------------- ingest
    def ingest(self, items: list[TelemetryInput]) -> dict[str, Any]:
        accepted, rejected = 0, []
        now = self.now()
        with self.lock, self.Session() as s:
            for i, item in enumerate(items):
                try:
                    self._ingest_one(s, item, now)
                    accepted += 1
                except IngestError as exc:
                    rejected.append({"index": i, "parameter": item.parameter, "error": str(exc)})
            s.commit()
        return {"accepted": accepted, "rejected": rejected}

    def _ingest_one(self, s: Session, item: TelemetryInput, now: datetime) -> None:
        pdef = self.reg.parameters.get(item.parameter)
        if pdef is None:
            raise IngestError(f"Unknown parameter '{item.parameter}'")
        if not pdef.available:
            raise IngestError(f"Parameter '{item.parameter}' is not instrumented in this configuration")
        if item.unit is not None and item.unit != pdef.unit:
            raise IngestError(f"Unit mismatch for {item.parameter}: expected '{pdef.unit}', got '{item.unit}'")
        if item.source not in SOURCES:
            raise IngestError(f"Invalid source '{item.source}'")
        if item.quality not in QUALITIES:
            raise IngestError(f"Invalid quality '{item.quality}'")
        ts = item.timestamp or now
        if ts.tzinfo is None:
            raise IngestError("Timestamp must include a timezone (UTC)")
        ts = ts.astimezone(timezone.utc)
        if ts > now + timedelta(seconds=5):
            raise IngestError("Timestamp is in the future")
        value = item.value
        if value is None and item.quality != "FAULT":
            raise IngestError("A value is required unless quality is FAULT")
        if value is not None and not math.isfinite(value):
            raise IngestError("Value must be a finite number")

        quality = item.quality
        meta = dict(item.metadata or {})
        reason = meta.get("reason") or "sensor reported a fault"
        if quality == "GOOD" and not (pdef.valid_min <= value <= pdef.valid_max):
            quality = "INVALID"
            reason = f"value {fmt(value)} {pdef.unit} outside plausible range {fmt(pdef.valid_min)}..{fmt(pdef.valid_max)}"
            meta["validation"] = reason
        st = self.state[pdef.id]
        late = st.timestamp is not None and ts < st.timestamp
        if late:
            meta["late"] = True
        s.add(TelemetryRecord(
            id=new_id(), mission_id=self.mission_id, crew_id=item.crew_id or (self.crew_id if pdef.category != "environmental" else None),
            parameter=pdef.id, category=pdef.category, value=value, unit=pdef.unit, timestamp=ts,
            source=item.source, quality=quality, meta=meta or None,
        ))
        if late:
            return  # stored for the record, never evaluated out of order
        st.value, st.timestamp, st.source, st.quality = value, ts, item.source, quality
        if quality in ("FAULT", "INVALID"):
            self._sensor_fault(s, pdef, ts, reason, item.source)
        elif quality == "GOOD":
            self._valid_sample(s, pdef, value, ts, item.source)
        # SUSPECT: stored and displayed, but never used to raise or resolve alerts.

    def _sensor_fault(self, s: Session, pdef: ParameterDef, ts: datetime, reason: str, source: str) -> None:
        st = self.state[pdef.id]
        st.fault, st.fault_reason = True, reason
        rule = f"FAULT-{pdef.id}"
        alert = self._open_alert(s, rule)
        if alert is None:
            self._raise(
                s, rule_id=rule, kind="SENSOR_FAULT", parameter=pdef.id, zone=pdef.zone,
                title=f"{pdef.short} SENSOR FAULT",
                message=f"{pdef.sensor}: {reason}. {pdef.label} is unavailable and is NOT assumed to be normal.",
                data_source=source, protocol_id=SENSOR_PROTOCOL, severity=pdef.stale_severity, unit=pdef.unit, value=None, ts=ts,
            )
        elif alert.lifecycle == am.RECOVERY:
            self._record(s, alert, am.on_condition(alert, pdef.stale_severity, ts, pdef.recovery_hold_s, True), ts)

    def _valid_sample(self, s: Session, pdef: ParameterDef, value: float, ts: datetime, source: str) -> None:
        st = self.state[pdef.id]
        st.fault, st.fault_reason = False, None
        st.last_valid_value, st.last_valid_ts, st.last_valid_source = value, ts, source
        st.trend.append((ts, value))
        th = self.effective_thresholds(pdef)
        st.observations.append(Observation(value, classify(value, th), ts))

        for prefix in ("FAULT-", "STALE-"):
            alert = self._open_alert(s, prefix + pdef.id)
            if alert is not None:
                self._record(s, alert, am.on_condition(alert, Severity.NOMINAL, ts, pdef.recovery_hold_s, True), ts)

        if th.is_empty():
            return
        rule = f"TH-{pdef.id}"
        alert = self._open_alert(s, rule)
        sev = evaluate(value, th, alert is not None)
        if alert is None:
            if sev is not None and sev > Severity.NOMINAL:
                title, msg = self._threshold_text(pdef, value, sev)
                self._raise(s, rule_id=rule, kind="THRESHOLD", parameter=pdef.id, zone=pdef.zone, title=title, message=msg,
                            data_source=source, protocol_id=pdef.protocol, severity=sev, unit=pdef.unit, value=value, ts=ts)
            return
        alert.last_value = value
        if sev is None:
            transitions = am.on_hysteresis_band(alert, ts)
        else:
            transitions = am.on_condition(alert, sev, ts, pdef.recovery_hold_s, pdef.auto_clear)
            if any(t.event_type in ("ESCALATED", "DEESCALATED", "RECURRED") for t in transitions):
                alert.title, alert.message = self._threshold_text(pdef, value, Severity(alert.severity))
                alert.data_source = source
        self._record(s, alert, transitions, ts)

    # -------------------------------------------------------------- monitor
    def tick_monitor(self) -> None:
        """Stale-data detection and R.I.D.G.E. correlation. Called once per second."""
        now = self.now()
        with self.lock, self.Session() as s:
            for pid, pdef in self.reg.parameters.items():
                if not pdef.available or pdef.stale_after_s <= 0:
                    continue
                st = self.state[pid]
                ref = st.last_valid_ts or self.started_at
                age = (now - ref).total_seconds()
                if age <= pdef.stale_after_s:
                    continue
                rule = f"STALE-{pid}"
                alert = self._open_alert(s, rule)
                if alert is None:
                    last = f"last valid sample {age:.0f} s ago" if st.last_valid_ts else "no valid sample received yet"
                    self._raise(
                        s, rule_id=rule, kind="DATA_STALE", parameter=pid, zone=pdef.zone,
                        title=f"{pdef.short} DATA STALE",
                        message=f"No valid {pdef.label} data within {pdef.stale_after_s:g} s ({last}). The last value is NOT assumed current.",
                        data_source=st.last_valid_source or "NONE", protocol_id=SENSOR_PROTOCOL,
                        severity=pdef.stale_severity, unit=pdef.unit, value=None, ts=now,
                    )
                elif alert.lifecycle == am.RECOVERY:
                    self._record(s, alert, am.on_condition(alert, pdef.stale_severity, now, pdef.recovery_hold_s, True), now)
            self._evaluate_ridge(s, now)
            s.commit()

    def _evaluate_ridge(self, s: Session, now: datetime) -> None:
        history = {pid: list(st.observations) for pid, st in self.state.items()}
        horizon = now - timedelta(days=2)
        swx = [e.start_time for e in s.scalars(select(RadiationEvent).where(RadiationEvent.start_time >= horizon))]
        swx += [t for t in s.scalars(select(NasaWeatherCache.peak_time).where(NasaWeatherCache.peak_time >= horizon)) if t]
        findings, inactive = evaluate_rules(self.reg.ridge_rules, history, swx, now)
        for f in findings:
            alert = self._open_alert(s, f.rule_id)
            if alert is None:
                first = next((x["factor"] for x in f.factors if x["factor"] in self.reg.parameters), None)
                zone = self.reg.parameters[first].zone if first else "radiation"
                self._raise(
                    s, rule_id=f.rule_id, kind="CORRELATION", parameter=first, zone=zone,
                    title=f"R.I.D.G.E.: {f.title}", message=f"{f.explanation} {UNCERTAINTY}",
                    data_source="R.I.D.G.E. (derived)", protocol_id=None, severity=Severity.ADVISORY,
                    unit=None, value=None, ts=now, factors=f.factors,
                )
            else:
                alert.factors = f.factors
                if alert.lifecycle == am.RECOVERY:
                    self._record(s, alert, am.on_condition(alert, Severity.ADVISORY, now, RIDGE_RECOVERY_HOLD_S, True), now)
        for rid in inactive:
            alert = self._open_alert(s, rid)
            if alert is not None:
                self._record(s, alert, am.on_condition(alert, Severity.NOMINAL, now, RIDGE_RECOVERY_HOLD_S, True), now)

    def tick(self) -> None:
        """One second of onboard processing: simulator (if enabled), then monitor."""
        if self.simulator.enabled:
            self.simulator.tick()
        self.tick_monitor()
        if self.fitness is not None:
            self.fitness.tick()

    # ------------------------------------------------------- crew actions
    def _get_alert(self, s: Session, alert_id: str) -> AlertEvent:
        alert = s.get(AlertEvent, alert_id)
        if alert is None:
            raise NotFoundError(f"Alert {alert_id} not found")
        return alert

    def _alert_action(self, alert_id: str, fn: Callable[[Session, AlertEvent, datetime], list[am.Transition]]) -> dict[str, Any]:
        now = self.now()
        with self.lock, self.Session() as s:
            alert = self._get_alert(s, alert_id)
            transitions = fn(s, alert, now)
            self._record(s, alert, transitions, now)
            s.commit()
            return self.serialize_alert(alert)

    def acknowledge(self, alert_id: str) -> dict[str, Any]:
        return self._alert_action(alert_id, lambda s, a, now: am.acknowledge(a, now))

    def silence(self, alert_id: str) -> dict[str, Any]:
        return self._alert_action(alert_id, lambda s, a, now: am.silence(a, now))

    def silence_all(self) -> int:
        now = self.now()
        count = 0
        with self.lock, self.Session() as s:
            for alert in s.scalars(select(AlertEvent).where(AlertEvent.lifecycle != am.CLEARED)):
                tr = am.silence(alert, now)
                count += bool(tr)
                self._record(s, alert, tr, now)
            s.commit()
        return count

    def confirm_step(self, alert_id: str, step_index: int) -> dict[str, Any]:
        def do(s: Session, alert: AlertEvent, now: datetime) -> list[am.Transition]:
            proto = self.reg.protocols.get(alert.protocol_id or "")
            if proto is None:
                raise am.TransitionError("No countermeasure protocol is configured for this alert")
            tr = am.confirm_step(alert, step_index, len(proto.steps), now)
            if any(t.event_type == "COUNTERMEASURE_STEP_CONFIRMED" for t in tr):
                s.add(CountermeasureExecution(alert_id=alert.id, protocol_id=proto.id, step_index=step_index, confirmed_at=now, actor="CREW"))
            return tr

        return self._alert_action(alert_id, do)

    def resolve(self, alert_id: str) -> dict[str, Any]:
        return self._alert_action(alert_id, lambda s, a, now: am.clear(a, now, actor="CREW"))

    # --------------------------------------------------------- PVT / psych
    def submit_pvt(self, reaction_times_ms: list[float], misses: int, false_starts: int, duration_s: float, source: str = "CREW_INPUT") -> dict[str, Any]:
        rts = [float(x) for x in reaction_times_ms if math.isfinite(x) and 100 <= x <= 3000]
        if len(rts) != len(reaction_times_ms):
            raise IngestError("Reaction times must be between 100 and 3000 ms (faster responses count as false starts)")
        now = self.now()
        mean_rt = round(statistics.fmean(rts), 1) if rts else None
        median_rt = round(statistics.median(rts), 1) if rts else None
        with self.lock, self.Session() as s:
            row = PVTResult(
                id=new_id(), crew_id=self.crew_id, timestamp=now, duration_s=duration_s,
                stimuli=len(rts) + misses, responses=len(rts), mean_rt_ms=mean_rt, median_rt_ms=median_rt,
                lapses=sum(1 for x in rts if x > 500), misses=misses, false_starts=false_starts,
                reaction_times_ms=rts, source=source,
            )
            s.add(row)
            self.enqueue(s, "PVT_RESULT", self.serialize_pvt(row))
            s.add(MissionLogEntry(timestamp=now, category="CREW", message=f"PVT completed: mean RT {fmt(mean_rt)} ms, {misses} missed, {false_starts} false starts", source=source))
            s.commit()
            result = self.serialize_pvt(row)
        if mean_rt is not None:
            self.ingest([TelemetryInput("pvt_mean_rt", mean_rt, "ms", now, source, "GOOD")])
        return result

    def pvt_history(self, limit: int = 20) -> dict[str, Any]:
        with self.Session() as s:
            rows = s.scalars(select(PVTResult).order_by(desc(PVTResult.timestamp)).limit(limit)).all()
        items = [self.serialize_pvt(r) for r in rows]
        baseline = None
        prev = [r.mean_rt_ms for r in rows[1:6] if r.mean_rt_ms is not None]
        if prev:
            baseline = round(statistics.fmean(prev), 1)
        latest = rows[0].mean_rt_ms if rows else None
        delta = round(latest - baseline, 1) if latest is not None and baseline is not None else None
        return {"results": items, "baseline_mean_rt_ms": baseline, "latest_delta_ms": delta}

    @staticmethod
    def serialize_pvt(r: PVTResult) -> dict[str, Any]:
        return {
            "id": r.id, "timestamp": iso(r.timestamp), "duration_s": r.duration_s, "stimuli": r.stimuli,
            "responses": r.responses, "mean_rt_ms": r.mean_rt_ms, "median_rt_ms": r.median_rt_ms,
            "lapses": r.lapses, "misses": r.misses, "false_starts": r.false_starts,
            "reaction_times_ms": r.reaction_times_ms, "source": r.source,
        }

    def submit_psych(self, mood: int, stress: int, fatigue: int, sleep_quality: int, notes: str, private: bool) -> dict[str, Any]:
        now = self.now()
        with self.lock, self.Session() as s:
            row = PsychologicalAssessment(id=new_id(), crew_id=self.crew_id, timestamp=now, mood=mood, stress=stress,
                                          fatigue=fatigue, sleep_quality=sleep_quality, notes=notes, private=private)
            s.add(row)
            if not private:
                self.enqueue(s, "PSYCH_ASSESSMENT_SHARED", self.serialize_psych(row))
            s.add(MissionLogEntry(timestamp=now, category="CREW", message="Self-assessment recorded" + (" (private)" if private else " (shared with flight surgeon)"), source="CREW_INPUT"))
            s.commit()
            return self.serialize_psych(row)

    def psych_history(self, limit: int = 30) -> list[dict[str, Any]]:
        with self.Session() as s:
            rows = s.scalars(select(PsychologicalAssessment).order_by(desc(PsychologicalAssessment.timestamp)).limit(limit)).all()
        return [self.serialize_psych(r) for r in rows]

    @staticmethod
    def serialize_psych(r: PsychologicalAssessment) -> dict[str, Any]:
        return {"id": r.id, "timestamp": iso(r.timestamp), "mood": r.mood, "stress": r.stress, "fatigue": r.fatigue,
                "sleep_quality": r.sleep_quality, "notes": r.notes, "private": r.private}

    # -------------------------------------------------------- serialization
    def serialize_alert(self, a: AlertEvent) -> dict[str, Any]:
        pdef = self.reg.parameters.get(a.parameter or "")
        hold = pdef.recovery_hold_s if pdef else RIDGE_RECOVERY_HOLD_S
        if a.kind in ("THRESHOLD",) and pdef is None:
            hold = RIDGE_RECOVERY_HOLD_S
        return {
            "id": a.id, "rule_id": a.rule_id, "kind": a.kind, "parameter": a.parameter, "zone": a.zone,
            "title": a.title, "message": a.message, "data_source": a.data_source,
            "simulated": a.data_source == "SIMULATED", "protocol_id": a.protocol_id,
            "severity": Severity(a.severity).name, "peak_severity": Severity(a.peak_severity).name,
            "lifecycle": a.lifecycle, "acknowledged": a.acknowledged, "silenced": a.silenced,
            "cm_status": a.cm_status, "cm_steps_done": list(a.cm_steps_done or []), "unit": a.unit,
            "trigger_value": a.trigger_value, "last_value": a.last_value, "occurrence_count": a.occurrence_count,
            "recovery_since": iso(a.recovery_since), "resolution_verified": a.resolution_verified,
            "recovery_hold_s": hold, "factors": a.factors, "created_at": iso(a.created_at), "updated_at": iso(a.updated_at),
            "cleared_at": iso(a.cleared_at), "cleared_by": a.cleared_by, "states": am.display_states(a),
            "audio_required": am.audio_required(a), "can_clear": a.lifecycle == am.RECOVERY and a.resolution_verified,
        }

    def list_alerts(self, include_cleared: bool = False, limit: int = 100) -> list[dict[str, Any]]:
        with self.Session() as s:
            q = select(AlertEvent)
            if not include_cleared:
                q = q.where(AlertEvent.lifecycle != am.CLEARED)
            rows = s.scalars(q.order_by(desc(AlertEvent.updated_at)).limit(limit)).all()
            out = [self.serialize_alert(a) for a in rows]
        if not include_cleared:
            out.sort(key=lambda a: (-Severity[a["severity"]], a["lifecycle"] != am.ACTIVE, a["created_at"]))
        return out

    def recent_cleared(self, limit: int = 8) -> list[dict[str, Any]]:
        with self.Session() as s:
            rows = s.scalars(select(AlertEvent).where(AlertEvent.lifecycle == am.CLEARED).order_by(desc(AlertEvent.cleared_at)).limit(limit)).all()
            return [self.serialize_alert(a) for a in rows]

    def alert_detail(self, alert_id: str) -> dict[str, Any]:
        with self.Session() as s:
            a = self._get_alert(s, alert_id)
            data = self.serialize_alert(a)
            hist = s.scalars(select(AlertHistory).where(AlertHistory.alert_id == alert_id).order_by(AlertHistory.id)).all()
            data["history"] = [{"id": h.id, "timestamp": iso(h.timestamp), "event_type": h.event_type, "detail": h.detail,
                                "actor": h.actor, "severity": Severity(h.severity).name, "lifecycle": h.lifecycle} for h in hist]
            return data

    def parameter_states(self) -> list[dict[str, Any]]:
        now = self.now()
        out = []
        for pid, pdef in self.reg.parameters.items():
            st = self.state[pid]
            age = (now - st.last_valid_ts).total_seconds() if st.last_valid_ts else None
            if not pdef.available:
                status = "NOT_INSTRUMENTED"
            elif st.fault:
                status = "SENSOR_FAULT"
            elif st.last_valid_ts is None:
                status = "NO_DATA"
            elif pdef.stale_after_s > 0 and age is not None and age > pdef.stale_after_s:
                status = "STALE"
            else:
                status = "OK"
            th = self.effective_thresholds(pdef)
            band = classify(st.last_valid_value, th).name if st.last_valid_value is not None and status == "OK" else None
            out.append({
                **pdef.to_public(),
                "status": status,
                "value": st.last_valid_value,
                "timestamp": iso(st.last_valid_ts),
                "age_s": round(age, 1) if age is not None else None,
                "source": st.last_valid_source,
                "latest_quality": st.quality,
                "fault_reason": st.fault_reason,
                "band": band,
                "effective_thresholds": th.as_dict(),
                "limits_context": self.limits_context(pdef),
                "trend": [[iso(t), v] for t, v in st.trend],
            })
        return out

    def timeline(self, limit: int = 40) -> list[dict[str, Any]]:
        with self.Session() as s:
            hist = s.execute(
                select(AlertHistory, AlertEvent.title, AlertEvent.data_source, AlertEvent.zone)
                .join(AlertEvent, AlertEvent.id == AlertHistory.alert_id)
                .order_by(desc(AlertHistory.id)).limit(limit)
            ).all()
            logs = s.scalars(select(MissionLogEntry).order_by(desc(MissionLogEntry.id)).limit(limit)).all()
        items = [{
            "id": f"A{h.id}", "timestamp": iso(h.timestamp), "category": "ALERT", "event_type": h.event_type,
            "severity": Severity(h.severity).name, "message": f"{title}: {h.event_type.replace('_', ' ')}" + (f" - {h.detail}" if h.detail else ""),
            "source": src, "alert_id": h.alert_id, "zone": zone, "actor": h.actor,
        } for h, title, src, zone in hist]
        items += [{"id": f"L{e.id}", "timestamp": iso(e.timestamp), "category": e.category, "event_type": e.category,
                   "severity": None, "message": e.message, "source": e.source, "alert_id": None, "zone": None, "actor": None} for e in logs]
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        return items[:limit]

    def events_since(self, since: int | None, limit: int = 50) -> tuple[list[dict[str, Any]], int]:
        """Alert history events after `since` - used by the UI for audio/voice cues."""
        with self.Session() as s:
            latest = s.scalar(select(func.max(AlertHistory.id))) or 0
            if since is None or since > latest:
                return [], latest
            rows = s.execute(
                select(AlertHistory, AlertEvent).join(AlertEvent, AlertEvent.id == AlertHistory.alert_id)
                .where(AlertHistory.id > since).order_by(AlertHistory.id).limit(limit)
            ).all()
            return [{
                "seq": h.id, "event_type": h.event_type, "alert_id": a.id, "title": a.title, "kind": a.kind,
                "severity": Severity(h.severity).name, "protocol_id": a.protocol_id, "silenced": a.silenced,
                "parameter": a.parameter, "timestamp": iso(h.timestamp),
            } for h, a in rows], latest

    def radiation_summary(self) -> dict[str, Any]:
        now = self.now()
        budget = float(self.reg.radiation.get("mission_dose_budget_mGy", 0) or 0)
        acc = self.state["accumulated_dose"].last_valid_value if "accumulated_dose" in self.state else None
        with self.Session() as s:
            events = s.scalars(select(RadiationEvent).where(RadiationEvent.start_time >= now - timedelta(days=30))
                               .order_by(desc(RadiationEvent.start_time)).limit(20)).all()
            ev = [{"id": e.id, "event_type": e.event_type, "source": e.source, "start_time": iso(e.start_time),
                   "peak_time": iso(e.peak_time), "class_type": e.class_type, "description": e.description, "link": e.link} for e in events]
        return {
            "dose_rate": self.state["dose_rate"].last_valid_value,
            "dose_rate_source": self.state["dose_rate"].last_valid_source,
            "accumulated_mGy": acc,
            "budget_mGy": budget,
            "budget_fraction": round(acc / budget, 4) if acc is not None and budget else None,
            "budget_provenance": "DEMONSTRATION",
            "events": ev,
            "note": "Space-weather events are context only. They are not astronaut dose measurements.",
        }

    def mission_info(self) -> dict[str, Any]:
        now = self.now()
        with self.Session() as s:
            m = s.get(Mission, self.mission_id)
            crew = s.scalars(select(CrewMember).where(CrewMember.mission_id == self.mission_id)).all()
            return {
                "id": m.id, "name": m.name, "environment": m.environment, "vehicle": m.vehicle,
                "met_start_utc": iso(m.met_start_utc), "met_seconds": int((now - m.met_start_utc).total_seconds()),
                "crew": [{"id": c.id, "name": c.name, "role": c.role, "monitored": c.monitored} for c in crew],
                "monitored_crew_id": self.crew_id,
            }

    def readiness(self, state: dict[str, Any], space_weather: dict[str, Any] | None = None) -> dict[str, Any]:
        """EVA decision support + triage focus, derived from an already built state snapshot."""
        sim = self.simulator.simulated_space_weather()
        if sim:
            risk, source = sim["space_weather_risk"], "SIMULATED scenario"
        else:
            risk = (space_weather or {}).get("space_weather_risk", "NOMINAL")
            source = "NASA DONKI" + (" placeholder" if (space_weather or {}).get("is_placeholder") else "")
        protocols = {pid: p.to_public() for pid, p in self.reg.protocols.items()}
        return {"eva": evaluate_eva_readiness(state, risk, source), "triage": evaluate_triage_focus(state, protocols)}

    def _classify_ksp_hazard(
        self,
        situation: str,
        body: str,
        altitude_m: float,
        g_force: float,
        mach: float,
        eva_active: bool,
    ) -> tuple[str, str]:
        """Classify active KSP flight telemetry into a medical/environmental hazard regime."""
        atmos_limits = {
            "kerbin": 70000.0,
            "eve": 90000.0,
            "duna": 50000.0,
            "laythe": 50000.0,
            "jool": 200000.0,
        }
        body_key = (body or "kerbin").strip().lower()
        atmos_limit = atmos_limits.get(body_key, 0.0)
        sit = (situation or "FLIGHT").strip().upper()

        # 1. Crew EVA in open space
        if eva_active:
            if atmos_limit == 0.0 or altitude_m >= atmos_limit * 0.5 or sit in ("ORBITING", "SUB_ORBITAL", "ESCAPING"):
                self.ksp_was_in_space = True
            return (
                "EVA_OPEN_SPACE",
                "EXTRAVEHICULAR ACTIVITY (EVA) — SUIT HYPOXIA & RADIATION EXPOSURE",
            )

        # 2. Open space / vacuum (above atmosphere or in orbit/trajectory around airless body)
        in_open_space = False
        if atmos_limit > 0.0 and altitude_m >= atmos_limit:
            in_open_space = True
        elif atmos_limit == 0.0 and sit in ("ORBITING", "SUB_ORBITAL", "ESCAPING", "DOCKED"):
            in_open_space = True
        elif sit in ("ORBITING", "ESCAPING") and altitude_m >= max(10000.0, atmos_limit * 0.95):
            in_open_space = True

        if in_open_space:
            self.ksp_was_in_space = True
            return (
                "OPEN_SPACE",
                "OPEN SPACE (VACUUM) — RADIATION STORM & ECLSS CO2 LOAD",
            )

        # 3. Atmospheric entry / aerobraking / high G-load
        descending = self.ksp_prev_alt is not None and (self.ksp_prev_alt - altitude_m) > 10.0 and altitude_m > 1000.0
        in_atmos_flight = (
            atmos_limit > 0.0
            and 250.0 < altitude_m < atmos_limit
            and sit in ("FLYING", "SUB_ORBITAL", "ORBITING", "ESCAPING")
        )
        if in_atmos_flight and (
            self.ksp_was_in_space
            or sit == "SUB_ORBITAL"
            or mach >= 1.15
            or g_force >= 1.85
            or descending
        ):
            return (
                "ATMOS_ENTRY",
                "ATMOSPHERIC ENTRY — G-LOAD TACHYCARDIA, BP DROP & THERMAL STRESS",
            )

        if sit in ("LANDED", "SPLASHED", "PRELAUNCH"):
            self.ksp_was_in_space = False

        return ("NOMINAL_PAD", "NOMINAL MODE (LAUNCH PAD / SURFACE)")

    def update_ksp_telemetry(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Receive live vessel & Kerbal crew state from the KSP 1 OrionMedKSP VesselModule."""
        now = self.now()
        with self.lock:
            self.ksp_last_seen = now
            situation = str(payload.get("situation") or "FLIGHT")
            body = str(payload.get("body") or "Kerbin")
            altitude_m = float(payload.get("altitude_m") or 0.0)
            g_force = float(payload.get("g_force") or 1.0)
            mach = float(payload.get("mach") or 0.0)
            eva_active = bool(payload.get("eva_active", False))

            hazard_phase, hazard_label = self._classify_ksp_hazard(
                situation=situation,
                body=body,
                altitude_m=altitude_m,
                g_force=g_force,
                mach=mach,
                eva_active=eva_active,
            )
            self.ksp_prev_alt = altitude_m

            if hazard_phase != self.ksp_current_phase:
                self.ksp_current_phase = hazard_phase
                if hazard_phase != "NOMINAL_PAD":
                    self.ksp_acked_phase = None
                    self.log("KSP_BRIDGE", f"KSP Flight Trigger [{hazard_phase}]: {hazard_label}", "SENSOR")

            self.ksp_telemetry = {
                "vessel_name": str(payload.get("vessel_name") or "UNKNOWN VESSEL"),
                "situation": situation,
                "body": body,
                "altitude_m": altitude_m,
                "g_force": g_force,
                "mach": mach,
                "met_s": float(payload.get("met_s") or 0.0),
                "eva_active": eva_active,
                "hazard_phase": hazard_phase,
                "hazard_label": hazard_label,
                "emotion": str(payload.get("emotion") or "Neutral"),
                "consciousness": str(payload.get("consciousness") or "Alert"),
                "primary_cause": str(payload.get("primary_cause") or hazard_label),
                "critical_timer_s": float(payload.get("critical_timer_s") or 0.0),
                "lethal_limit_s": float(payload.get("lethal_limit_s") or 30.0),
                "crew": list(payload.get("crew") or []),
            }

            if payload.get("ingest_biometrics", True):
                if hazard_phase != "NOMINAL_PAD" and self.ksp_acked_phase != hazard_phase:
                    if hazard_phase == "EVA_OPEN_SPACE":
                        if self.simulator.enabled and self.simulator.scenario != "hypoxia":
                            self.simulator.set_scenario("hypoxia")
                        overrides = {
                            "spo2": 81.4,
                            "cabin_o2": 17.8,
                            "cabin_pressure": 89.2,
                            "heart_rate": 134.0,
                            "resp_rate": 25.0,
                            "dose_rate": 460.0,
                        }
                        self.simulator.values.update(overrides)
                        self.ingest([
                            TelemetryInput("spo2", 81.4, "%", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("cabin_o2", 17.8, "%", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("cabin_pressure", 89.2, "kPa", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("heart_rate", 134.0, "bpm", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("resp_rate", 25.0, "br/min", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("dose_rate", 460.0, "uGy/h", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                        ])
                    elif hazard_phase == "OPEN_SPACE":
                        if self.simulator.enabled and self.simulator.scenario != "high_co2":
                            self.simulator.set_scenario("high_co2")
                        overrides = {
                            "cabin_co2": 8.2,
                            "dose_rate": 420.0,
                            "heart_rate": 118.0,
                            "resp_rate": 21.5,
                        }
                        self.simulator.values.update(overrides)
                        self.ingest([
                            TelemetryInput("cabin_co2", 8.2, "mmHg", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("dose_rate", 420.0, "uGy/h", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("heart_rate", 118.0, "bpm", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("resp_rate", 21.5, "br/min", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("pvt_mean_rt", 455.0, "ms", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                        ])
                    elif hazard_phase == "ATMOS_ENTRY":
                        if self.simulator.enabled and self.simulator.scenario != "hemorrhage":
                            self.simulator.set_scenario("hemorrhage")
                        g = max(2.0, g_force)
                        bp = max(68.0, round(76.0 - max(0.0, g - 2.5) * 2.5, 1))
                        hr = min(168.0, round(144.0 + max(0.0, g - 2.0) * 3.5, 1))
                        overrides = {
                            "bp_systolic": bp,
                            "heart_rate": hr,
                            "resp_rate": 24.5,
                            "hrv": 14.0,
                            "body_temp": 38.2,
                        }
                        self.simulator.values.update(overrides)
                        self.ingest([
                            TelemetryInput("bp_systolic", bp, "mmHg", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("heart_rate", hr, "bpm", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("resp_rate", 24.5, "br/min", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("hrv", 14.0, "ms", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                            TelemetryInput("body_temp", 38.2, "degC", now, "SENSOR", "GOOD", metadata={"ksp_hazard": hazard_phase}),
                        ])
                elif g_force >= 3.0 and self.simulator.scenario == "nominal":
                    hr = min(165.0, round(72.0 + (g_force - 1.0) * 14.5, 1))
                    rr = min(30.0, round(14.0 + (g_force - 1.0) * 2.2, 1))
                    bp = max(72.0, round(118.0 - max(0.0, g_force - 4.0) * 8.5, 1))
                    self.ingest([
                        TelemetryInput("heart_rate", hr, "bpm", now, "SENSOR", "GOOD", metadata={"ksp_g_force": g_force}),
                        TelemetryInput("resp_rate", rr, "br/min", now, "SENSOR", "GOOD", metadata={"ksp_g_force": g_force}),
                        TelemetryInput("bp_systolic", bp, "mmHg", now, "SENSOR", "GOOD", metadata={"ksp_g_force": g_force}),
                    ])
            return self.ksp_status()

    def ksp_status(self) -> dict[str, Any]:
        now = self.now()
        if self.ksp_last_seen is None:
            return {
                "connected": False,
                "last_seen": None,
                "age_s": None,
                "vessel_name": None,
                "situation": None,
                "body": None,
                "altitude_m": 0.0,
                "g_force": 0.0,
                "mach": 0.0,
                "met_s": 0.0,
                "eva_active": False,
                "hazard_phase": "NOMINAL_PAD",
                "hazard_label": None,
                "emotion": "Neutral",
                "consciousness": "Alert",
                "primary_cause": None,
                "critical_timer_s": 0.0,
                "lethal_limit_s": 30.0,
                "crew": [],
            }
        age = max(0.0, (now - self.ksp_last_seen).total_seconds())
        return {
            "connected": age <= 5.0,
            "last_seen": iso(self.ksp_last_seen),
            "age_s": round(age, 1),
            **self.ksp_telemetry,
        }

    def dashboard(self, since: int | None = None) -> dict[str, Any]:
        alerts = self.list_alerts()
        events, latest_seq = self.events_since(since)
        params = self.parameter_states()
        active = [a for a in alerts if a["lifecycle"] != am.CLEARED]
        worst = max((Severity[a["severity"]] for a in active), default=Severity.NOMINAL)
        instrumentation = [a for a in active if a["kind"] in ("SENSOR_FAULT", "DATA_STALE")]
        return {
            "server_time": iso(self.now()),
            "version": APP_VERSION,
            "mission": self.mission_info(),
            "mode": {
                "demo_mode": self.settings.demo_mode,
                "simulator_enabled": self.simulator.enabled,
                "scenario": self.simulator.scenario,
                "scenarios": self.simulator.scenario_list(),
            },
            "medical_status": worst.name,
            "system_health": {
                "status": "DEGRADED" if instrumentation else "NOMINAL",
                "detail": f"{len(instrumentation)} instrumentation alert(s)" if instrumentation else "All instrumented sensors reporting",
                "database": "OK",
                "rules_engine": "OK",
            },
            "master": {
                "warning": any(a["severity"] == "WARNING" and a["lifecycle"] == am.ACTIVE for a in active),
                "warning_unacked": any(a["severity"] == "WARNING" and not a["acknowledged"] for a in active),
                "caution": any(a["severity"] == "CAUTION" and a["lifecycle"] == am.ACTIVE for a in active),
                "caution_unacked": any(a["severity"] == "CAUTION" and not a["acknowledged"] for a in active),
                "audio_required": any(a["audio_required"] for a in active),
            },
            "zones": self.reg.zones,
            "parameters": params,
            "alerts": active,
            "recent_cleared": self.recent_cleared(8),
            "events": events,
            "latest_event_seq": latest_seq,
            "radiation": self.radiation_summary(),
            "sync": self.sync.status(),
            "timeline": self.timeline(30),
            "ksp": self.ksp_status(),
        }
