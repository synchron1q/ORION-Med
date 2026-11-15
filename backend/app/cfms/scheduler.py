# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS scheduler - deterministic, idempotent placement of exercise sessions.

Pure functions: no database and no clock access. The same inputs always give
the same output, and reconciling an already reconciled schedule changes
nothing: no duplicate sessions and no moves without a recorded reason.

Every change produces a Decision (original window, conflict, reason, new
window) that the service stores as planner history.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from app.cfms.config import ALL, DAY_H, FitnessConfig, MissionPlan, met_label, met_to_utc, utc_to_met_h

PLANNED, NOTIFIED, IN_PROGRESS = "PLANNED", "NOTIFIED", "IN_PROGRESS"
COMPLETED, ABORTED, MISSED, UNSCHEDULED, CANCELLED = "COMPLETED", "ABORTED", "MISSED", "UNSCHEDULED", "CANCELLED"
MOVABLE = (PLANNED, NOTIFIED)
OCCUPYING = (PLANNED, NOTIFIED, IN_PROGRESS)
OPEN = (PLANNED, NOTIFIED, UNSCHEDULED)
TERMINAL = (COMPLETED, ABORTED, MISSED, CANCELLED)


@dataclass(frozen=True)
class Activity:
    id: str
    type: str
    title: str
    crew: tuple[str, ...]
    start: datetime
    end: datetime
    device_id: str | None = None
    source: str = "BASELINE"  # BASELINE | MANUAL | SIMULATED | KRPC


@dataclass(frozen=True)
class Phase:
    id: str
    type: str
    title: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class Conflict:
    code: str
    ref: str
    text: str


@dataclass
class SessionState:
    id: str
    crew_id: str
    exercise_type: str
    day_index: int
    ordinal: int
    status: str
    device_id: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    attempt: int = 0
    conflict: str | None = None


@dataclass(frozen=True)
class Requirement:
    id: str
    crew_id: str
    crew_rank: int
    exercise_type: str
    ordinal: int
    day_index: int
    preferred_start: datetime


@dataclass
class Decision:
    session_id: str
    action: str
    trigger: str
    reason: str
    conflict_code: str | None = None
    conflict_ref: str | None = None
    from_start: datetime | None = None
    from_end: datetime | None = None
    from_device: str | None = None
    to_start: datetime | None = None
    to_end: datetime | None = None
    to_device: str | None = None


@dataclass
class Outcome:
    session: SessionState
    created: bool = False
    decisions: list[Decision] = field(default_factory=list)


@dataclass
class PlanningContext:
    now: datetime
    met_start: datetime
    cfg: FitnessConfig
    plan: MissionPlan
    activities: list[Activity]
    device_status: dict[str, str]
    phases: list[Phase] = field(init=False)

    def __post_init__(self) -> None:
        self.activities = sorted(self.activities, key=lambda a: (a.start, a.id))
        self.phases = build_phases(self.plan, self.met_start)

    @property
    def plan_start(self) -> datetime:
        return met_to_utc(self.met_start, self.plan.coverage[0])

    @property
    def plan_end(self) -> datetime:
        return met_to_utc(self.met_start, self.plan.coverage[1])

    def met(self, t: datetime | None) -> str:
        return met_label(self.met_start, t)


# ------------------------------------------------------------------ helpers
def session_id(day_index: int, crew_id: str, exercise_type: str, ordinal: int) -> str:
    return f"EX-D{day_index:03d}-{crew_id}-{exercise_type}-{ordinal}"


def day_bounds(ctx: PlanningContext, day_index: int) -> tuple[datetime, datetime]:
    return met_to_utc(ctx.met_start, day_index * DAY_H), met_to_utc(ctx.met_start, (day_index + 1) * DAY_H)


def day_of(met_start: datetime, t: datetime) -> int:
    return math.floor(utc_to_met_h(met_start, t) / DAY_H + 1e-9)


def _overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> bool:
    return a0 < b1 and b0 < a1


def build_phases(plan: MissionPlan, met_start: datetime) -> list[Phase]:
    return [Phase(p.id, p.type, p.title, met_to_utc(met_start, p.start_met_h), met_to_utc(met_start, p.end_met_h)) for p in plan.phases]


def expand_plan(plan: MissionPlan, met_start: datetime, start: datetime, end: datetime) -> list[Activity]:
    """Baseline activities overlapping [start - 1 day, end + 1 day]. Generated on the fly, never stored."""
    lo, hi = start - timedelta(days=1), end + timedelta(days=1)
    out: list[Activity] = []
    first, last = day_of(met_start, lo), day_of(met_start, hi)
    for day in range(first, last + 1):
        base = day * DAY_H
        if base < plan.coverage[0] or base + DAY_H > plan.coverage[1]:
            continue
        for t in plan.template:
            a0 = met_to_utc(met_start, base + t.start_h)
            out.append(Activity(f"{t.id}-D{day:03d}", t.type, t.title, t.crew, a0, a0 + timedelta(minutes=t.duration_min), t.device_id))
    for e in plan.events:
        a0 = met_to_utc(met_start, e.start_h)
        a1 = a0 + timedelta(minutes=e.duration_min)
        if _overlap(a0, a1, lo, hi):
            out.append(Activity(e.id, e.type, e.title, e.crew, a0, a1, e.device_id))
    return out


def requirements(ctx: PlanningContext) -> list[Requirement]:
    """Program sessions for every MET day that overlaps [now, now + horizon] inside plan coverage."""
    pol = ctx.cfg.policy
    first = day_of(ctx.met_start, ctx.now)
    last = day_of(ctx.met_start, ctx.now + timedelta(hours=pol.horizon_h))
    out: list[Requirement] = []
    for day in range(first, last + 1):
        ds, de = day_bounds(ctx, day)
        if de <= ctx.now or ds < ctx.plan_start or de > ctx.plan_end:
            continue
        for p in ctx.cfg.program:
            out.append(Requirement(session_id(day, p.crew_id, p.exercise_type, p.ordinal), p.crew_id, p.crew_rank,
                                   p.exercise_type, p.ordinal, day, ds + timedelta(hours=p.preferred_start_h)))
    return out


def preferred_start(ctx: PlanningContext, s: SessionState) -> datetime | None:
    p = ctx.cfg.program_item(s.crew_id, s.exercise_type, s.ordinal)
    if p is None:
        return None
    return day_bounds(ctx, s.day_index)[0] + timedelta(hours=p.preferred_start_h)


# ---------------------------------------------------------------- conflicts
def plan_conflict(ctx: PlanningContext, crew_id: str, start: datetime, end: datetime, day_index: int | None = None) -> Conflict | None:
    """Mission Plan constraints only: MET day, coverage, forbidden phases, activities with buffers."""
    if day_index is not None:
        ds, de = day_bounds(ctx, day_index)
        if start < ds or end > de:
            return Conflict("OUT_OF_DAY", f"D{day_index:03d}", f"Outside MET day {day_index}")
    if start < ctx.plan_start or end > ctx.plan_end:
        return Conflict("PLAN_COVERAGE", ctx.plan.plan_id, "Outside Mission Plan coverage")
    for ph in ctx.phases:
        if ph.type in ctx.cfg.forbidden_phase_types and _overlap(start, end, ph.start, ph.end):
            return Conflict("PHASE", ph.id, f"Mission phase '{ph.title}' ({ph.type}) forbids exercise")
    for a in ctx.activities:
        rule = ctx.cfg.activity_rules.get(a.type)
        if rule is None:
            continue
        if not (rule.scope == "vehicle" or ALL in a.crew or crew_id in a.crew):
            continue
        b0 = a.start - timedelta(minutes=rule.before_min)
        b1 = a.end + timedelta(minutes=rule.after_min)
        if _overlap(start, end, b0, b1):
            src = "" if a.source == "BASELINE" else f", {a.source}"
            buf = f" incl. buffers -{rule.before_min}/+{rule.after_min} min" if rule.before_min or rule.after_min else ""
            return Conflict("ACTIVITY", a.id, f"{a.type} '{a.title}' ({a.id}{src}){buf}")
    return None


def device_conflict(ctx: PlanningContext, device_id: str | None, start: datetime, end: datetime,
                    occ: list[SessionState], exclude_id: str) -> Conflict | None:
    if device_id is None or device_id not in ctx.cfg.devices:
        return Conflict("NO_DEVICE", str(device_id), "No device assigned")
    dev = ctx.cfg.devices[device_id]
    status = ctx.device_status.get(device_id, dev.initial_status)
    if status != "OPERATIONAL":
        return Conflict("DEVICE_STATUS", device_id, f"{dev.label} status {status}")
    for a in ctx.activities:
        if a.device_id == device_id and _overlap(start, end, a.start, a.end):
            return Conflict("DEVICE_MAINTENANCE", a.id, f"{dev.label} reserved: {a.title} ({a.id})")
    turn = timedelta(minutes=ctx.cfg.policy.device_turnaround_min)
    for o in occ:
        if o.id != exclude_id and o.device_id == device_id and o.start and o.end and _overlap(start, end, o.start - turn, o.end + turn):
            return Conflict("DEVICE_BUSY", o.id, f"{dev.label} in use by {o.crew_id} ({o.id}), turnaround {ctx.cfg.policy.device_turnaround_min} min")
    return None


def crew_conflict(ctx: PlanningContext, crew_id: str, start: datetime, end: datetime,
                  occ: list[SessionState], exclude_id: str) -> Conflict | None:
    gap = timedelta(minutes=ctx.cfg.policy.min_gap_same_crew_min)
    for o in occ:
        if o.id != exclude_id and o.crew_id == crew_id and o.start and o.end and _overlap(start, end, o.start - gap, o.end + gap):
            return Conflict("CREW_SESSION", o.id, f"Within {ctx.cfg.policy.min_gap_same_crew_min} min of session {o.id}")
    return None


def device_candidates(ctx: PlanningContext, exercise_type: str, prefer: str | None = None) -> list[str]:
    classes = ctx.cfg.exercise_types[exercise_type].device_classes
    ordered = [d.id for c in classes for d in ctx.cfg.devices.values() if d.device_class == c]
    if prefer in ordered:
        ordered.remove(prefer)
        ordered.insert(0, prefer)
    return ordered


def choose_device(ctx: PlanningContext, exercise_type: str, start: datetime, end: datetime, occ: list[SessionState],
                  exclude_id: str, prefer: str | None = None) -> tuple[str | None, Conflict | None]:
    first: Conflict | None = None
    cands = device_candidates(ctx, exercise_type, prefer)
    for d in cands:
        c = device_conflict(ctx, d, start, end, occ, exclude_id)
        if c is None:
            return d, None
        first = first or c
    return None, first or Conflict("NO_DEVICE", exercise_type, f"No device configured for {exercise_type}")


def _ceil_grid(ctx: PlanningContext, t: datetime) -> datetime:
    slot_s = ctx.cfg.policy.slot_min * 60
    k = math.ceil(round((t - ctx.met_start).total_seconds(), 6) / slot_s)
    return ctx.met_start + timedelta(seconds=k * slot_s)


def candidate_starts(ctx: PlanningContext, day_index: int, duration: timedelta, anchor: datetime, earliest: datetime,
                     exact_first: bool = False) -> list[datetime]:
    """Grid starts inside the MET day: forward from the anchor, then backward from it."""
    ds, de = day_bounds(ctx, day_index)
    lo, hi = max(ds, earliest), de - duration
    if lo > hi:
        return []
    grid: list[datetime] = []
    t = _ceil_grid(ctx, lo)
    step = timedelta(minutes=ctx.cfg.policy.slot_min)
    while t <= hi:
        grid.append(t)
        t += step
    out = [t for t in grid if t >= anchor] + [t for t in reversed(grid) if t < anchor]
    if exact_first and lo not in out:
        out.insert(0, lo)
    return out


def find_slot(ctx: PlanningContext, s: SessionState, anchor: datetime, earliest: datetime, occ: list[SessionState],
              prefer_device: str | None = None, exact_first: bool = False
              ) -> tuple[tuple[datetime, datetime, str] | None, Conflict]:
    dur = timedelta(minutes=ctx.cfg.exercise_types[s.exercise_type].duration_min)
    cands = candidate_starts(ctx, s.day_index, dur, anchor, earliest, exact_first)
    seen: list[Conflict] = []
    for t in cands:
        e = t + dur
        c = plan_conflict(ctx, s.crew_id, t, e, s.day_index) or crew_conflict(ctx, s.crew_id, t, e, occ, s.id)
        if c is None:
            d, c = choose_device(ctx, s.exercise_type, t, e, occ, s.id, prefer_device)
            if d is not None:
                return (t, e, d), Conflict("NONE", "", "")
        if all((c.code, c.ref) != (x.code, x.ref) for x in seen):
            seen.append(c)
    if not seen:
        return None, Conflict("NO_TIME", f"D{s.day_index:03d}", f"No time left in MET day {s.day_index}")
    more = f" (+{len(seen) - 3} more)" if len(seen) > 3 else ""
    text = f"{len(cands)} window(s) checked; blockers: " + "; ".join(x.text for x in seen[:3]) + more
    return None, Conflict(seen[0].code, seen[0].ref, text)


# --------------------------------------------------------------- reconcile
def _rank(ctx: PlanningContext, s: SessionState) -> int:
    p = ctx.cfg.program_item(s.crew_id, s.exercise_type, s.ordinal)
    return p.crew_rank if p else 999


def reconcile(ctx: PlanningContext, sessions: list[SessionState], trigger: str) -> list[Outcome]:
    """Bring the stored schedule in line with the plan. Idempotent: a second run changes nothing.

    IN_PROGRESS sessions must be passed with start/end set to their occupied window.
    """
    pol = ctx.cfg.policy
    now = ctx.now
    lead = timedelta(minutes=pol.placement_lead_min)
    grace = timedelta(minutes=pol.start_grace_min)
    work = {s.id: replace(s) for s in sessions}
    outcomes: dict[str, Outcome] = {}

    def note(s: SessionState, d: Decision, created: bool = False) -> None:
        o = outcomes.setdefault(s.id, Outcome(s, created))
        o.created = o.created or created
        o.decisions.append(d)

    def by_time(s: SessionState) -> tuple:
        return (s.start or datetime.max.replace(tzinfo=now.tzinfo), s.id)

    queue: list[tuple[str, str, datetime, Conflict | None]] = []

    # 1. Missed sessions (not started within the start grace).
    for s in sorted(work.values(), key=by_time):
        if s.status in MOVABLE and s.start is not None and now > s.start + grace:
            retry = s.attempt < pol.max_reschedules
            s.status = MISSED
            reason = f"Not started by {ctx.met(s.start + grace)} (start grace {pol.start_grace_min} min)"
            if not retry:
                reason += f"; automatic reschedule limit ({pol.max_reschedules}) reached"
            note(s, Decision(s.id, "MISSED", trigger, reason, "MISSED", s.id, s.start, s.end, s.device_id))
            if retry:
                queue.append((s.id, "MISSED", now + lead, Conflict("MISSED", s.id, reason)))

    # 2. Unscheduled sessions whose MET day is over.
    for s in sorted(work.values(), key=lambda s: s.id):
        if s.status == UNSCHEDULED and day_bounds(ctx, s.day_index)[1] <= now:
            s.status = MISSED
            note(s, Decision(s.id, "MISSED", trigger, f"No valid window before the end of MET day {s.day_index}", "NO_SLOT", f"D{s.day_index:03d}"))

    # 3. Sessions removed from the training program.
    for s in sorted(work.values(), key=lambda s: s.id):
        if s.status in OPEN and ctx.cfg.program_item(s.crew_id, s.exercise_type, s.ordinal) is None:
            s.status = CANCELLED
            note(s, Decision(s.id, "CANCELLED", trigger, "No longer in the DEMONSTRATION training program (fitness.yaml)",
                             "PROGRAM", s.exercise_type, s.start, s.end, s.device_id))

    # 4. Validate the kept schedule in time order.
    occ: list[SessionState] = [s for s in work.values() if s.status == IN_PROGRESS]
    for s in sorted((x for x in work.values() if x.status in MOVABLE), key=by_time):
        c = plan_conflict(ctx, s.crew_id, s.start, s.end, s.day_index) or crew_conflict(ctx, s.crew_id, s.start, s.end, occ, s.id)
        if c is None:
            dc = device_conflict(ctx, s.device_id, s.start, s.end, occ, s.id)
            if dc is None:
                occ.append(s)
                continue
            d, _ = choose_device(ctx, s.exercise_type, s.start, s.end, occ, s.id)
            if d is not None:
                note(s, Decision(s.id, "DEVICE_REASSIGNED", trigger, f"Conflict: {dc.text}", dc.code, dc.ref,
                                 s.start, s.end, s.device_id, s.start, s.end, d))
                s.device_id = d
                occ.append(s)
                continue
            c = dc
        queue.append((s.id, "MOVE", s.start, c))

    # 5. New requirements in the horizon.
    created: set[str] = set()
    for r in requirements(ctx):
        if r.id not in work:
            work[r.id] = SessionState(r.id, r.crew_id, r.exercise_type, r.day_index, r.ordinal, UNSCHEDULED)
            created.add(r.id)
            queue.append((r.id, "NEW", r.preferred_start, None))

    # 6. Retry sessions that had no valid window.
    for s in sorted(work.values(), key=lambda s: s.id):
        if s.status == UNSCHEDULED and s.id not in created:
            queue.append((s.id, "RETRY", preferred_start(ctx, s) or day_bounds(ctx, s.day_index)[0], None))

    # 7. Place in a fixed order.
    queue.sort(key=lambda q: (work[q[0]].day_index, _rank(ctx, work[q[0]]), work[q[0]].ordinal, q[0]))
    for sid, kind, anchor, conflict in queue:
        s = work[sid]
        earliest = max(now + lead, day_bounds(ctx, s.day_index)[0])
        old = (s.start, s.end, s.device_id)
        found, diag = find_slot(ctx, s, anchor, earliest, occ, s.device_id if kind == "MOVE" else None)
        if found is not None:
            st, en, dev = found
            if kind == "NEW":
                d = Decision(sid, "CREATED", trigger, f"Initial placement (program preference {ctx.met(anchor)})",
                             to_start=st, to_end=en, to_device=dev)
            elif kind == "MOVE":
                d = Decision(sid, "MOVED", trigger, f"Conflict: {conflict.text}", conflict.code, conflict.ref, *old, st, en, dev)
            elif kind == "MISSED":
                s.attempt += 1
                d = Decision(sid, "RESCHEDULED", trigger, f"Rescheduled after missed session (attempt {s.attempt}/{pol.max_reschedules})",
                             "MISSED", sid, *old, st, en, dev)
            else:
                d = Decision(sid, "PLACED", trigger, "A valid window became available", s.conflict, None, to_start=st, to_end=en, to_device=dev)
            s.status, s.start, s.end, s.device_id, s.conflict = PLANNED, st, en, dev, None
            occ.append(s)
            note(s, d, sid in created)
            continue
        if kind == "RETRY":
            continue  # still no valid window: nothing changed, nothing recorded
        if kind == "MISSED":
            note(s, Decision(sid, "NOT_RESCHEDULED", trigger, f"No valid window left in MET day {s.day_index}: {diag.text}",
                             diag.code, diag.ref, *old))
            continue
        why = f"Conflict: {conflict.text}. " if conflict else ""
        note(s, Decision(sid, "UNSCHEDULABLE", trigger, f"{why}No valid window in MET day {s.day_index}: {diag.text}",
                         (conflict or diag).code, (conflict or diag).ref, *old), sid in created)
        s.status, s.start, s.end, s.device_id, s.conflict = UNSCHEDULED, None, None, None, diag.code

    return [outcomes[k] for k in sorted(outcomes)]


def reschedule_earliest(ctx: PlanningContext, sessions: list[SessionState], sid: str, trigger: str = "CREW_REQUEST"
                        ) -> tuple[Outcome | None, Conflict | None]:
    """Crew request: move one open session to the earliest valid window from now (same MET day)."""
    work = {s.id: replace(s) for s in sessions}
    s = work[sid]
    if s.status not in OPEN:
        return None, Conflict("STATE", sid, f"Session is {s.status}")
    occ = [o for o in work.values() if o.status in OCCUPYING and o.id != sid]
    earliest = (ctx.now + timedelta(seconds=59)).replace(second=0, microsecond=0)
    found, diag = find_slot(ctx, s, earliest, earliest, occ, s.device_id, exact_first=True)
    if found is None:
        return None, diag
    st, en, dev = found
    if s.status in MOVABLE and s.start is not None and st >= s.start:
        return None, Conflict("NO_EARLIER", sid, "No earlier valid window than the current one")
    old = (s.start, s.end, s.device_id)
    d = Decision(sid, "CREW_REQUEST", trigger, "Crew requested the earliest valid window", "CREW_REQUEST", sid, *old, st, en, dev)
    s.status, s.start, s.end, s.device_id, s.conflict = PLANNED, st, en, dev, None
    return Outcome(s, False, [d]), None
