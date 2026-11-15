<!-- AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md -->
# CFMS — Crew Fitness Management System (optional module)

> **Status (v1.0.6):** core (scheduler, Safety Gate, scoped Medical Clearance, session lifecycle, DEMONSTRATION
> exercise profile, API), screen 3 FITNESS with one full demonstration scenario, Recovery Monitor.
> Next stage: optional read-only kRPC adapter.
>
> **All medical values, training norms and tolerances are DEMONSTRATION. The Mission Plan and the exercise
> equipment are SIMULATED.** The application does not control any real hardware and is not a NASA exercise prescription.

## Enable

CFMS is off by default; with it off, ORION-MED behaves exactly as v1.0.3 (no CFMS tables are created,
`/api/v1/fitness/*` returns 404, `/api/state.fitness` is `{"enabled": false}`).

```
# .env
ORION_CFMS_ENABLED=true
```

## Flow

```
config/mission_plan.yaml ─┐
(SIMULATED baseline)      ├─► Scheduler ─► Safety Gate ─► ExerciseSession ─► Recovery Monitor (next stage)
SQLite RuntimeActivity ───┘   (deterministic,  (BLOCKED /      (crew confirms
(unplanned additions)          idempotent)      CLEARANCE_      start; DEMO
config/fitness.yaml ──────────────────────────► REQUIRED /      profile during
(program, devices, policy)                      READY_PER_PLAN) the session)
```

Existing modules are used read-only: HevCore (parameter states, active alerts), CrewMember list,
mission log and sync queue. HevCore thresholds and the alert state machine are not modified.

## Single source of truth

| What | Where | Notes |
|---|---|---|
| Baseline Mission Plan (phases, daily template, events) | `config/mission_plan.yaml` | Never copied into SQLite. Content hash recorded with every decision. A changed file is detected at start (`PLAN_REVISION`) and replanned deterministically. |
| Unplanned activities | SQLite `cfms_runtime_activities` | Ids `RT-0001…`; cannot edit or cancel a baseline activity. Sources: MANUAL, SIMULATED, KRPC. |
| Program, devices, rules, profiles | `config/fitness.yaml` | Contains **no** medical clearance. |
| Sessions, decisions, clearances, device status | SQLite `cfms_*` tables | Runtime records only. |

## Scheduler (`backend/app/cfms/scheduler.py`)

Pure functions, no clock or database: the same inputs always give the same schedule.

- One session per requirement `(MET day, crew member, exercise type, ordinal)`; the id is derived from it
  (`EX-D003-CM-1-AEROBIC-1`), so a replan or a restart can never create a duplicate.
- Placement on a 15-minute MET grid, forward from the program's preferred time, then backward, inside the MET day.
- Constraints: forbidden mission phases, every planned activity of the crew member with its buffers
  (sleep, EVA, EVA preparation, maneuvers and critical operations are vehicle-wide, meals), device status,
  device maintenance windows, device turnaround, minimum gap between two sessions of one crew member.
  Cruise is not treated as automatically safe.
- A valid session is never moved. A session moves only on a recorded conflict, and does not move back when
  the conflict disappears.
- Missed sessions (not started within the grace) are rescheduled up to `max_reschedules`, then closed as MISSED.
- Every change is stored in `cfms_schedule_decisions`: action, trigger, original window, conflict, reason,
  new window, plan hash. Actions: CREATED, MOVED, DEVICE_REASSIGNED, MISSED, RESCHEDULED, NOT_RESCHEDULED,
  UNSCHEDULABLE, PLACED, CANCELLED, CREW_REQUEST.

## Safety Gate (`backend/app/cfms/gate.py`)

| Result | When |
|---|---|
| **BLOCKED** | Any MASTER WARNING; a CAUTION on the cabin (environment, radiation) for everyone; a CAUTION on the monitored crew member; cabin atmosphere not monitored; plan conflict or forbidden phase; device not OPERATIONAL. **A Medical Clearance never overrides BLOCKED.** |
| **CLEARANCE_REQUIRED** | Incomplete physiological data (no data, stale, sensor fault); an ADVISORY; a crew member without a biosensor (CM-2…CM-4 in this prototype). Incomplete data is never treated as normal. |
| **READY_PER_PLAN** | No blocker found by the DEMONSTRATION rules. Not a medical authorization: the crew confirms the start. |

Recovery of the previous session of the same crew member (monitored crew member, within 24 h): RECOVERING → BLOCKED;
REVIEW or DATA_INCOMPLETE → CLEARANCE_REQUIRED, and only a clearance recorded **after** that finding is accepted.

### Medical Clearance

A runtime record limited to **one crew member, one exercise type and a validity period**
(at most `clearance.max_validity_h`, 24 h). It must cover the whole session window, can be revoked, and is logged
and sent to the ground queue. The issuer is a SIMULATED record in this prototype. There is no clearance in YAML.

## During a session

Starting a session records the gate result, the clearance (if any) and the applied DEMONSTRATION profile
(`EXP-AEROBIC-DEMO`, `EXP-RESISTIVE-DEMO`). The profile only produces a display band (IN_TARGET, ABOVE_TARGET,
REVIEW, STOP_RECOMMENDED, DATA_INCOMPLETE, …) and mission-log entries. Global HEV-1 alerts keep firing with
their normal limits; an alert raised during a confirmed session is logged with the exercise context and linked
in `/api/state.fitness.alert_context`. It is never suppressed.

## Recovery Monitor (`backend/app/cfms/recovery.py`)

After a session of the monitored crew member, heart rate is observed for `recovery.window_min` (10 min, DEMONSTRATION):

| Status | Rule |
|---|---|
| RECOVERING | First 60 s, or still above pre-session HR + 10 bpm inside the window |
| RECOVERED | Back within pre-session HR + 10 bpm and the 60-s drop meets the criterion. Not an authorization. |
| REVIEW | 60-s drop below 12 bpm after an elevated response (end HR ≥ pre-session + 20 bpm), or not back within the window |
| DATA_INCOMPLETE | No biosensor (CM-2…CM-4), HR missing at start/end, at +60 s or at the end of the window |

The final result is stored once with the session, logged and sent to the ground queue. View: RECOVERY MONITOR
(status per crew member, recovery curve with the baseline and +60 s markers, criteria, recent sessions).

## Screen 3 · FITNESS

Shown only when CFMS is enabled (tab "3 FITNESS", key `3`).

| View | Content |
|---|---|
| CREW SCHEDULE | Next session and gate per crew member; 24-hour timeline (vehicle, crew, devices) with buffers (dashed), forbidden phases (hatched), runtime additions (dashed border) and a gate dot per session; session panel (gate reasons, CONFIRM START, COMPLETE, ABORT with reason, REQUEST EARLIEST WINDOW, Medical Clearance form fixed to the selected crew member and exercise type, planner history); in-session monitor; clearances and CFMS notifications |
| MISSION PLANNER | Decision history (original → new window, conflict, reason, trigger); insert an unplanned activity; runtime additions with cancel; sessions without a valid window; plan source of truth (id, revision, hash) |
| EQUIPMENT STATUS | SIMULATED devices with status control and assigned sessions; DEMONSTRATION program, monitoring profiles and buffers |
| RECOVERY MONITOR | Latest recovery per crew member with its effect on the next session; recovery curve and metrics; criteria; recent sessions |

The COMMAND screen shows a compact "Next exercise · CFMS" card for the monitored crew member.

## Demonstration scenario

On a fresh database (the demo plan starts at MET 076:30), with `ORION_CFMS_ENABLED=true`:

1. Press `3`. CM-1 (biosensor) is READY PER PLAN; CM-2…CM-4 are CLEARANCE REQUIRED (no biosensor).
2. Select CM-2 → MEDICAL CLEARANCE… → RECORD: the gate becomes READY PER PLAN for CM-2 · AEROBIC only.
3. Select CM-1 → CONFIRM START. The simulator applies a SIMULATED exercise load: heart rate rises to ~125 bpm,
   the global MASTER CAUTION fires with the unchanged 110 bpm limit and R.I.D.G.E. links it to physical activity.
   The in-session monitor shows IN TARGET for the DEMONSTRATION profile and that the alert is not suppressed.
4. COMPLETE. RECOVERY MONITOR shows RECOVERING (the next CM-1 session is BLOCKED meanwhile), then RECOVERED after 60 s
   with the 60-s drop and the time back to baseline. The crew clears the heart-rate alert after verified recovery.
5. MISSION PLANNER → ADD AND REPLAN (unplanned maneuver in 10 min): conflicting sessions are moved or reported without
   a window, each with original window, conflict, reason and new window.
6. EQUIPMENT STATUS → RES-01 FAULT: resistive sessions lose their window; OPERATIONAL: they are placed again.

Automated: `frontend/e2e/cfms-fitness-scenario.spec.ts` (screenshots 10–15 in `docs/screenshots/`).

## API (`/api/v1/fitness`)

| Method | Path | Purpose |
|---|---|---|
| GET | `/status` | Same block as `/api/state.fitness` |
| GET | `/config` | Program, devices, rules, profiles (DEMONSTRATION) |
| GET | `/schedule?crew_id=` | Sessions from today, with the gate for upcoming ones |
| GET | `/sessions/{id}` | Session, gate, decision history |
| POST | `/sessions/{id}/start` · `/complete` · `/abort` · `/request-earliest` | Lifecycle; start returns 409 with the gate unless READY_PER_PLAN |
| GET | `/plan` | Baseline + runtime activities with origin labels |
| POST / DELETE | `/plan/activities`, `/plan/activities/{RT-id}` | Unplanned activity (exactly one of `start_met_h`, `start_utc`, `start_in_min`) |
| GET | `/decisions?session_id=` | Planner history |
| GET | `/recovery` | Recovery Monitor: results, curves, criteria |
| POST | `/replan` | Run the planner now (idempotent) |
| GET / POST | `/equipment`, `/equipment/{id}` | SIMULATED device status |
| GET / POST | `/clearances`, `/clearances/{id}/revoke` | Scoped Medical Clearance |

Example (conflict and replan):

```bash
curl -X POST localhost:8000/api/v1/fitness/plan/activities -H "Content-Type: application/json" \
  -d '{"activity_type":"MANEUVER","title":"Unplanned attitude maneuver","start_in_min":15,"duration_min":20}'
curl "localhost:8000/api/v1/fitness/decisions?limit=5"
```

## Limitations

- Demonstration rules and numbers; not validated against flight rules or medical criteria.
- Only CM-1 has a (simulated) biosensor stream; the other crew members always need a Medical Clearance.
- Device status is entered manually or by the simulator; there is no hardware link.
