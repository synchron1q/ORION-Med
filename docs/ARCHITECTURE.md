# Architecture

ORION-MED // HEV-1 is a modular monolith: one FastAPI process (decision support engine, simulator, integrations, local storage) and one React single-page application. The backend also serves the built interface, so a judge runs a single process on `http://localhost:8000`.

## Layers

| Layer | Code | Responsibility |
|---|---|---|
| 1. Crew interface | `frontend/src` | Avionics dashboard, Digital Human Twin, alerts, countermeasure guide, radiation, environment, mission log, simulator, PVT, self-check, voice |
| 2. Decision support engine | `backend/app/engine`, `backend/app/services/core.py` | Ingest, validation, threshold rules, alert state machine, stale/fault detection, R.I.D.G.E. |
| 3. Local storage | `backend/app/models.py`, SQLite | Telemetry, alerts + history, countermeasure executions, PVT, self-checks, mission configuration, sync queue, NASA cache |
| 4. External data | `backend/app/integrations` | NASA DONKI (FLR, SEP) and OSDR references; cached, never blocking |
| 5. Offline & sync | `backend/app/services/sync.py`, `frontend/public/sw.js`, `frontend/src/services/offlineCache.ts` | Ordered, idempotent Earth sync queue; PWA shell; IndexedDB snapshot and crew-input outbox |

## Data flow

```
sensor / simulator ──► HevCore.ingest()
                         ├─ validate (parameter, unit, finite, timestamp, plausible range)
                         ├─ store TelemetryRecord (source + quality)
                         ├─ FAULT / out-of-range ─► SENSOR_FAULT alert
                         └─ GOOD ─► rules.evaluate() ─► alert_machine ─► AlertEvent + AlertHistory + SyncQueueItem
1 Hz tick ──► simulator.tick() (demo) ─► tick_monitor(): DATA_STALE detection + R.I.D.G.E. correlation
UI ──► GET /api/state (1 Hz) ─► dashboard snapshot + NASA DONKI context (from SQLite cache)
```

The simulator calls exactly the same `ingest()` as a real sensor (`POST /api/v1/telemetry`). There is no separate demo alert path.

## Alert model

Each alert instance owns its state; dimensions are independent instead of one global enum:

- **severity**: ADVISORY / CAUTION / WARNING (escalation re-alarms: ACK and SILENCE are reset)
- **lifecycle**: ACTIVE → RECOVERY → CLEARED; RECOVERY → ACTIVE on relapse (`RECURRED`)
- **acknowledged / silenced** flags
- **countermeasure**: NONE / AVAILABLE / IN_PROGRESS / COMPLETED
- **kind**: THRESHOLD / SENSOR_FAULT / DATA_STALE / CORRELATION

Rules:
- ACK = seen + audio silenced. It never resolves, deletes or clears.
- Confirming countermeasure steps records crew actions only.
- RECOVERY starts when fresh valid data is inside the limits by the hysteresis margin. Resolution is verified only after `recovery_hold_s` of continuous fresh nominal data. Drifting back into the hysteresis band revokes verification.
- CLEAR is allowed only after verified resolution (two-step button in the UI, HTTP 409 otherwise). Advisory-type rules may auto-clear when configured (`auto_clear`).
- Missing or faulty data never feeds recovery: an open threshold alert stays ACTIVE while its sensor is stale.
- Repeated violations after CLEAR create a new instance; history is kept forever.

Named states of the specification (`WARNING`, `ACKNOWLEDGED`, `SILENCED`, `COUNTERMEASURE_IN_PROGRESS`, `RECOVERY`, `CLEARED`, `SENSOR_FAULT`, `DATA_STALE` …) are derived per instance in `alert_machine.display_states()`.

## R.I.D.G.E.

Rules in `config/demo_thresholds.yaml` (`ridge_rules`) list conditions (`min_severity` or comparison) that must all be observed within `window_s`, plus optional `any_of` conditions and a space-weather window. A finding is an ADVISORY with contributing factors, timestamps and an uncertainty statement. Original measurements are not modified.

## EVA readiness and triage focus (`engine/readiness.py`)

Reworked from the team's operational-readiness concept. Computed for every `/api/state` from the snapshot already built by the engine — no extra thresholds:
- **Gates:** radiation (dose rate, accumulated dose vs. demonstration budget, space-weather context), cabin atmosphere (CO2, O2, pressure), cardiorespiratory (HR, SpO2, RR), alertness (PVT, sleep). Each gate is CLEAR / REVIEW / HOLD from the configured bands, or UNKNOWN when data is stale, faulty or missing.
- **Overall:** HOLD_RECOMMENDED > DATA_INCOMPLETE > REVIEW > NO_BLOCKERS. Wording is decision support; the system never declares an EVA safe.
- **Triage focus:** picks the checklist to open first from the active alerts (highest severity, then a fixed priority list), adds correlated R.I.D.G.E. findings as context. Never suppresses an alarm and never names a diagnosis.

## Screens

The interface is one page with switchable views (state `screen` in the Zustand store, tabs in the status bar, keys 1/2/3): COMMAND (`components/ActionCentricHud.tsx`), ENGINEERING (the full panel grid) and, only with CFMS enabled, FITNESS (`modules/fitness/`). All render only data from the HEV-1 core.

## NASA DONKI integration

`integrations/nasa_donki.py`: async `httpx` (5 s timeout), FLR + SEP for the last 7 days, `NasaWeatherCache` table with a 15-minute TTL. `/api/state` never waits for NASA: the context is built from SQLite and a single background refresh is scheduled when the cache is stale. Failed refreshes back off for 5 minutes (DEMO_KEY quota). If `/DONKI/FLR` answers 404, flares come from `/DONKI/notifications?type=FLR` (significant flares only); the per-feed status shows the endpoint used. Tiers: `LIVE`, `CACHED_OFFLINE`, `OFFLINE_BASELINE` (labeled placeholder). DONKI never raises alerts or changes simulator scenarios; the SOLAR FLARE scenario shows its own labeled simulated event.

## Key decisions

| Decision | Reason |
|---|---|
| Single normalized `TelemetryRecord` table with `category` | One ingest/validation path for all parameter types |
| Protocols in YAML, not in the database | Countermeasures are structured configuration, reviewable and never generated at runtime |
| Polling at 1 Hz instead of WebSocket | Simple, robust offline behavior; events since last sequence drive audio cues |
| Global engine lock | Simulator, monitor and crew actions see one consistent state |
| SQLite WAL, auto-created | No server, survives restarts |

## CFMS (optional, `ORION_CFMS_ENABLED=true`)

`backend/app/cfms/` is a separate package with its own SQLAlchemy metadata (tables created only when enabled).
Flow: Mission Plan (`config/mission_plan.yaml` baseline + SQLite runtime additions) → deterministic scheduler →
Safety Gate → ExerciseSession → Recovery Monitor (next stage). It reads HevCore parameter states and active alerts,
writes to the mission log and the sync queue, and is ticked from `HevCore.tick()`. It never changes HevCore
thresholds or alert states. Details: [CFMS.md](CFMS.md).
