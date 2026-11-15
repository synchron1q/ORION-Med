# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS configuration loaders.

config/mission_plan.yaml - SIMULATED baseline Mission Plan. It is the only
source of the baseline; it is never copied into SQLite (see models.py).
config/fitness.yaml      - DEMONSTRATION program, SIMULATED equipment, policy.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

import yaml

from app.core.registry import ConfigError

ALL = "ALL"
SCOPES = ("crew", "vehicle")
DEVICE_STATUSES = ("OPERATIONAL", "DEGRADED", "FAULT", "MAINTENANCE")
DAY_H = 24.0


@dataclass(frozen=True)
class ActivityRule:
    type: str
    scope: str
    before_min: int
    after_min: int


@dataclass(frozen=True)
class ExerciseType:
    id: str
    label: str
    duration_min: int
    device_classes: tuple[str, ...]
    profile_id: str


@dataclass(frozen=True)
class Device:
    id: str
    label: str
    device_class: str
    initial_status: str


@dataclass(frozen=True)
class ProgramItem:
    crew_id: str
    crew_rank: int
    exercise_type: str
    ordinal: int
    preferred_start_h: float


@dataclass(frozen=True)
class ExerciseProfile:
    id: str
    label: str
    heart_rate_pct: dict[str, float]
    spo2: dict[str, float]
    reference: str | None = None

    def heart_rate_bpm(self, hrmax: float | None) -> dict[str, float]:
        if not hrmax:
            return {}
        return {k: round(v * hrmax / 100.0) for k, v in self.heart_rate_pct.items()}


@dataclass(frozen=True)
class RecoveryCriteria:
    window_min: float
    hrr60_min_bpm: float
    baseline_tolerance_bpm: float
    elevated_response_bpm: float
    validity_h: float


@dataclass(frozen=True)
class SchedulerPolicy:
    slot_min: int
    horizon_h: float
    notify_lead_min: int
    placement_lead_min: int
    start_early_min: int
    start_grace_min: int
    max_reschedules: int
    min_gap_same_crew_min: int
    device_turnaround_min: int
    replan_interval_s: float


@dataclass(frozen=True)
class FitnessConfig:
    provenance: str
    policy: SchedulerPolicy
    activity_rules: dict[str, ActivityRule]
    forbidden_phase_types: frozenset[str]
    exercise_types: dict[str, ExerciseType]
    devices: dict[str, Device]
    program: tuple[ProgramItem, ...]
    profiles: dict[str, ExerciseProfile]
    required_parameters: tuple[str, ...]
    required_cabin_parameters: tuple[str, ...]
    clearance_max_validity_h: float
    clearance_issuer_label: str
    simulated_load: dict[str, dict[str, float]]
    recovery: RecoveryCriteria
    crew_profiles: dict[str, dict[str, float]]
    exercise_alarm_policy: str
    exercise_hr_alarm_pct: dict[str, float]

    def hrmax(self, crew_id: str) -> float | None:
        v = (self.crew_profiles.get(crew_id) or {}).get("hrmax_bpm")
        return float(v) if v else None

    def rule(self, activity_type: str) -> ActivityRule:
        return self.activity_rules[activity_type]

    def program_item(self, crew_id: str, exercise_type: str, ordinal: int) -> ProgramItem | None:
        for p in self.program:
            if p.crew_id == crew_id and p.exercise_type == exercise_type and p.ordinal == ordinal:
                return p
        return None


@dataclass(frozen=True)
class PlanPhase:
    id: str
    type: str
    title: str
    start_met_h: float
    end_met_h: float


@dataclass(frozen=True)
class PlanItem:
    """A template item (start_h within a MET day) or an event (absolute start_met_h)."""

    id: str
    type: str
    title: str
    start_h: float
    duration_min: int
    crew: tuple[str, ...]
    device_id: str | None


@dataclass(frozen=True)
class MissionPlan:
    plan_id: str
    revision: str
    provenance: str
    coverage: tuple[float, float]
    phases: tuple[PlanPhase, ...]
    template: tuple[PlanItem, ...]
    events: tuple[PlanItem, ...]
    content_hash: str

    def baseline_ids(self) -> set[str]:
        return {e.id for e in self.events} | {t.id for t in self.template}


def _read(path: Path) -> tuple[dict[str, Any], bytes]:
    if not path.is_file():
        raise ConfigError(f"Missing CFMS configuration file: {path}")
    raw = path.read_bytes()
    data = yaml.safe_load(raw) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: top level must be a mapping")
    return data, raw


def _crew(value: Any, crew_ids: set[str], where: str) -> tuple[str, ...]:
    items = tuple(str(c) for c in (value or [ALL]))
    for c in items:
        if c != ALL and c not in crew_ids:
            raise ConfigError(f"{where}: unknown crew member {c}")
    if ALL in items and len(items) > 1:
        raise ConfigError(f"{where}: ALL cannot be combined with individual crew members")
    return items


def load_fitness_config(config_dir: Path, crew_ids: Iterable[str]) -> FitnessConfig:
    data, _ = _read(config_dir / "fitness.yaml")
    crew_set = set(crew_ids)
    s = data.get("scheduler") or {}
    policy = SchedulerPolicy(
        slot_min=int(s.get("slot_min", 15)),
        horizon_h=float(s.get("horizon_h", 48)),
        notify_lead_min=int(s.get("notify_lead_min", 15)),
        placement_lead_min=int(s.get("placement_lead_min", 10)),
        start_early_min=int(s.get("start_early_min", 15)),
        start_grace_min=int(s.get("start_grace_min", 15)),
        max_reschedules=int(s.get("max_reschedules", 2)),
        min_gap_same_crew_min=int(s.get("min_gap_same_crew_min", 120)),
        device_turnaround_min=int(s.get("device_turnaround_min", 15)),
        replan_interval_s=float(s.get("replan_interval_s", 5)),
    )
    if not 24 <= policy.horizon_h <= 72:
        raise ConfigError("fitness.yaml: scheduler.horizon_h must be within 24-72 h")
    if policy.slot_min <= 0 or 60 % policy.slot_min:
        raise ConfigError("fitness.yaml: scheduler.slot_min must divide 60")

    rules: dict[str, ActivityRule] = {}
    for t, r in (data.get("activity_rules") or {}).items():
        scope = r.get("scope", "crew")
        if scope not in SCOPES:
            raise ConfigError(f"fitness.yaml: activity rule {t}: invalid scope {scope}")
        rules[t] = ActivityRule(t, scope, int(r.get("before_min", 0)), int(r.get("after_min", 0)))

    devices: dict[str, Device] = {}
    for d in data.get("devices") or []:
        status = d.get("initial_status", "OPERATIONAL")
        if status not in DEVICE_STATUSES:
            raise ConfigError(f"fitness.yaml: device {d.get('id')}: invalid status {status}")
        if "SIMULATED" not in str(d.get("label", "")):
            raise ConfigError(f"fitness.yaml: device {d.get('id')} label must state SIMULATED")
        devices[d["id"]] = Device(d["id"], d["label"], d["class"], status)
    classes = {d.device_class for d in devices.values()}

    profiles: dict[str, ExerciseProfile] = {}
    for pid, p in (data.get("exercise_profiles") or {}).items():
        pct = dict(p.get("heart_rate_pct_hrmax") or {})
        if set(pct) != {"target_low", "target_high", "review_above", "stop_above"}:
            raise ConfigError(f"fitness.yaml: profile {pid}: heart_rate_pct_hrmax needs target_low, target_high, review_above, stop_above")
        profiles[pid] = ExerciseProfile(pid, p.get("label", pid), pct, dict(p.get("spo2") or {}), p.get("reference"))

    types: dict[str, ExerciseType] = {}
    for tid, t in (data.get("exercise_types") or {}).items():
        dc = tuple(t.get("device_classes") or [])
        if not dc or any(c not in classes for c in dc):
            raise ConfigError(f"fitness.yaml: exercise type {tid}: unknown or missing device class")
        if t.get("profile") not in profiles:
            raise ConfigError(f"fitness.yaml: exercise type {tid}: unknown profile {t.get('profile')}")
        types[tid] = ExerciseType(tid, t.get("label", tid), int(t["duration_min"]), dc, t["profile"])

    program: list[ProgramItem] = []
    for rank, (crew_id, items) in enumerate((data.get("program") or {}).items()):
        if crew_id not in crew_set:
            raise ConfigError(f"fitness.yaml: program: unknown crew member {crew_id}")
        for i, it in enumerate(items or []):
            if it.get("type") not in types:
                raise ConfigError(f"fitness.yaml: program {crew_id}: unknown exercise type {it.get('type')}")
            h = float(it.get("preferred_start_h", 0))
            if not 0 <= h < DAY_H:
                raise ConfigError(f"fitness.yaml: program {crew_id}: preferred_start_h must be within 0-24")
            program.append(ProgramItem(crew_id, rank, it["type"], i + 1, h))

    policy_name = str(data.get("exercise_alarm_policy", "global"))
    if policy_name not in ("global", "context_hrmax"):
        raise ConfigError("fitness.yaml: exercise_alarm_policy must be global or context_hrmax")
    alarm_pct = {k: float(v) for k, v in (data.get("exercise_hr_alarm_pct_hrmax") or {"caution_high": 95, "warning_high": 100}).items()}
    if not 80 <= alarm_pct.get("caution_high", 0) <= alarm_pct.get("warning_high", 0) <= 105:
        raise ConfigError("fitness.yaml: exercise_hr_alarm_pct_hrmax must satisfy 80 <= caution_high <= warning_high <= 105")
    crew_profiles = {cid: dict(v or {}) for cid, v in (data.get("crew_profiles") or {}).items() if cid in crew_set}
    for cid, prof in crew_profiles.items():
        if not 120 <= float(prof.get("hrmax_bpm", 0)) <= 220:
            raise ConfigError(f"fitness.yaml: crew_profiles {cid}: hrmax_bpm must be within 120-220")
    gate = data.get("safety_gate") or {}
    rec = data.get("recovery") or {}
    if float(rec.get("window_min", 10)) < 2:
        raise ConfigError("fitness.yaml: recovery.window_min must be at least 2 minutes")
    clearance = data.get("clearance") or {}
    max_validity = float(clearance.get("max_validity_h", 24))
    if max_validity <= 0 or max_validity > 72:
        raise ConfigError("fitness.yaml: clearance.max_validity_h must be within (0, 72]")
    return FitnessConfig(
        provenance=str(data.get("provenance", "DEMONSTRATION / SIMULATED")),
        policy=policy,
        activity_rules=rules,
        forbidden_phase_types=frozenset(data.get("forbidden_phase_types") or []),
        exercise_types=types,
        devices=devices,
        program=tuple(program),
        profiles=profiles,
        required_parameters=tuple(gate.get("required_parameters") or ["heart_rate", "spo2"]),
        required_cabin_parameters=tuple(gate.get("required_cabin_parameters") or ["cabin_co2", "cabin_o2", "cabin_pressure"]),
        clearance_max_validity_h=max_validity,
        clearance_issuer_label=str(clearance.get("issuer_label", "Medical officer (SIMULATED)")),
        simulated_load={t: {k: float(v) for k, v in (vals or {}).items()} for t, vals in (data.get("simulated_load") or {}).items()
                        if t in types},
        crew_profiles=crew_profiles,
        exercise_alarm_policy=policy_name,
        exercise_hr_alarm_pct=alarm_pct,
        recovery=RecoveryCriteria(
            window_min=float(rec.get("window_min", 10)),
            hrr60_min_bpm=float(rec.get("hrr60_min_bpm", 12)),
            baseline_tolerance_bpm=float(rec.get("baseline_tolerance_bpm", 10)),
            elevated_response_bpm=float(rec.get("elevated_response_bpm", 20)),
            validity_h=float(rec.get("validity_h", 24)),
        ),
    )


def load_mission_plan(config_dir: Path, crew_ids: Iterable[str], cfg: FitnessConfig) -> MissionPlan:
    data, raw = _read(config_dir / "mission_plan.yaml")
    crew_set = set(crew_ids)
    cov = data.get("coverage_met_h") or [0, 720]
    coverage = (float(cov[0]), float(cov[1]))

    phases: list[PlanPhase] = []
    for p in data.get("phases") or []:
        phases.append(PlanPhase(p["id"], p["type"], p.get("title", p["id"]), float(p["start_met_h"]), float(p["end_met_h"])))
    phases.sort(key=lambda p: p.start_met_h)
    for a, b in zip(phases, phases[1:]):
        if b.start_met_h < a.end_met_h:
            raise ConfigError(f"mission_plan.yaml: phases {a.id} and {b.id} overlap")

    def item(d: dict[str, Any], start_key: str, where: str) -> PlanItem:
        if d.get("type") not in cfg.activity_rules:
            raise ConfigError(f"mission_plan.yaml: {where} {d.get('id')}: activity type {d.get('type')} has no rule in fitness.yaml")
        dev = d.get("device_id")
        if dev is not None and dev not in cfg.devices:
            raise ConfigError(f"mission_plan.yaml: {where} {d['id']}: unknown device {dev}")
        if int(d["duration_min"]) <= 0:
            raise ConfigError(f"mission_plan.yaml: {where} {d['id']}: duration must be positive")
        return PlanItem(str(d["id"]), d["type"], d.get("title", d["id"]), float(d[start_key]), int(d["duration_min"]),
                        _crew(d.get("crew"), crew_set, f"mission_plan.yaml {where} {d['id']}"), dev)

    template = tuple(item(d, "start_h", "daily_template") for d in data.get("daily_template") or [])
    events = tuple(item(d, "start_met_h", "event") for d in data.get("events") or [])
    ids = [x.id for x in template + events]
    if len(ids) != len(set(ids)):
        raise ConfigError("mission_plan.yaml: duplicate activity ids")
    if any(i.upper().startswith("RT-") for i in ids):
        raise ConfigError("mission_plan.yaml: ids starting with RT- are reserved for runtime activities")
    return MissionPlan(
        plan_id=str(data.get("plan_id", "PLAN")),
        revision=str(data.get("revision", "1")),
        provenance=str(data.get("provenance", "SIMULATED MISSION PLAN")),
        coverage=coverage,
        phases=tuple(phases),
        template=template,
        events=events,
        content_hash=hashlib.sha256(raw).hexdigest()[:12],
    )


def met_to_utc(met_start: datetime, met_h: float) -> datetime:
    return met_start + timedelta(hours=met_h)


def utc_to_met_h(met_start: datetime, t: datetime) -> float:
    return (t - met_start).total_seconds() / 3600.0


def met_label(met_start: datetime, t: datetime | None) -> str:
    """MET as HHH:MM (hours since MET 0), e.g. 'MET 076:45'."""
    if t is None:
        return "MET --:--"
    minutes = int(round((t - met_start).total_seconds() / 60.0))
    sign = "-" if minutes < 0 else ""
    minutes = abs(minutes)
    return f"MET {sign}{minutes // 60:03d}:{minutes % 60:02d}"
