# Changelog

## 1.0.6 — 2026-11-15
- CFMS stage 3: **Recovery Monitor** (`backend/app/cfms/recovery.py`, DEMONSTRATION criteria in `config/fitness.yaml` → `recovery`). After a session of the monitored crew member the heart rate is observed for 10 min: 60-s and 120-s drop, time back to pre-session HR + 10 bpm. Statuses RECOVERING / RECOVERED / REVIEW / DATA_INCOMPLETE; crew members without a biosensor are always DATA_INCOMPLETE. Missing data is never treated as normal.
- Final results are stored once with the session (existing JSON field, no schema change), written to the mission log and sent to the ground queue (`CFMS_RECOVERY`).
- Safety Gate: while recovery is observed the next session of that crew member is BLOCKED; REVIEW or DATA_INCOMPLETE make it CLEARANCE_REQUIRED, and only a Medical Clearance recorded after that finding can cover it.
- Screen 3 FITNESS: fourth view **RECOVERY MONITOR** (status per crew member, recovery curve with baseline and +60 s markers, metrics, criteria, recent sessions); recovery line in the session panel; COMMAND card shows recovery in progress.
- API `GET /api/v1/fitness/recovery`; `recovery` in `/api/state.fitness`.
- End-to-end CFMS scenario extended with the recovery step (screenshot 15).
- Tests: 131 backend, 24 frontend, 2 end-to-end.

## 1.0.5 — 2026-11-14
- CFMS stage 2: **screen 3 FITNESS** (key `3`, shown only with `ORION_CFMS_ENABLED=true`) with three views:
  CREW SCHEDULE (next session and safety gate per crew member, 24-hour Mission Plan timeline for crew and devices with buffers, forbidden phases and runtime additions, session panel with crew-confirmed start, complete, abort, earliest-window request and a Medical Clearance form scoped to the selected crew member and exercise type, in-session monitor, clearances and CFMS notifications),
  MISSION PLANNER (full decision history, insert an unplanned activity, runtime additions, sessions without a valid window, plan source of truth),
  EQUIPMENT STATUS (SIMULATED devices with status control and assigned sessions, DEMONSTRATION program, profiles and buffers).
- COMMAND screen: "Next exercise · CFMS" card (in-session heart rate and DEMONSTRATION profile band while exercising).
- Mission simulator: SIMULATED exercise load for the monitored crew member during a confirmed session (`simulated_load` in `config/fitness.yaml`), through the normal ingest path. A global MASTER CAUTION fires with unchanged limits and R.I.D.G.E. links it to physical activity.
- Planner: a session without a valid window now lists the distinct blockers that were checked.
- End-to-end scenario `cfms-fitness-scenario.spec.ts` (plan → gate → scoped clearance → monitored session → replanning → equipment fault); screenshots 10–14.
- Tests: 121 backend, 23 frontend, 2 end-to-end (the CFMS scenario is skipped when CFMS is off).

## 1.0.4 — 2026-11-14
- New optional module **CFMS — Crew Fitness Management System**, core stage. Off by default; enabled only with `ORION_CFMS_ENABLED=true`. With it off the application behaves as 1.0.3 and creates no CFMS tables.
- `config/mission_plan.yaml` (SIMULATED) is the single source of the baseline Mission Plan; SQLite stores only runtime additions (`RT-` activities) and CFMS records. A changed plan file is detected by content hash and replanned.
- `config/fitness.yaml` (DEMONSTRATION): daily program, SIMULATED equipment with neutral names, activity buffers, forbidden phases, in-session exercise profiles. No medical clearance in YAML.
- Deterministic, idempotent scheduler: one session per requirement (stable id), no moves without a recorded conflict, missed-session rescheduling with a limit, full decision history (original window, conflict, reason, new window, plan hash).
- Safety Gate: BLOCKED / CLEARANCE_REQUIRED / READY_PER_PLAN. Medical Clearance is scoped to one crew member, one exercise type and at most 24 h, and never overrides active critical alerts, forbidden phases, plan conflicts, equipment limits or an unmonitored cabin atmosphere.
- Session lifecycle (notify, start on crew confirmation, complete, abort, crew request for the earliest window). The DEMONSTRATION exercise profile is logged with the session; global HEV-1 limits are unchanged and alerts are never suppressed.
- REST API `/api/v1/fitness/*`, `fitness` block in `/api/state`, `cfms_enabled` in `/api/v1/health`. Documentation: `docs/CFMS.md`.
- Tests: 120 backend (33 new for CFMS), 19 frontend, end-to-end walkthrough passes with CFMS off and on.

## 1.0.3 — 2026-11-14
- Merged team work: hand-made Digital Human Twin (anatomical SVG), Action-Centric HUD concept, operational-readiness concept, `dev.bat` / `rebuild.bat` / `stop.bat`.
- Interface: two switchable screens on one page — 1 COMMAND (HUD with the Digital Human Twin) and 2 ENGINEERING (full panels); tabs in the status bar and keys 1/2.
- HUD reworked to use only HEV-1 core data (no local telemetry or verdict copies), English-only text, real scenario buttons.
- `engine/readiness.py` reworked: four EVA decision-support gates built on the engine thresholds, UNKNOWN for missing data, triage focus from active alerts; no diagnoses, no alarm suppression, no standard-compliance claims. New `GET /api/v1/readiness`; `readiness` added to `/api/state`. The forced `reset-all` clear was not adopted (alerts clear only after verified resolution).
- New simulator scenario HYPOXIA (SpO2 and cabin O2 decrease).
- `stop.bat` stops whole process trees; `dev.bat` uses absolute paths and checks the virtual environment.
- Tests: 86 backend, 19 frontend, end-to-end walkthrough across both screens.

## 1.0.2 — 2026-11-14
- NASA DONKI: when `/DONKI/FLR` returns HTTP 404 (endpoint unavailable on api.nasa.gov), solar flares are read from `/DONKI/notifications?type=FLR`. Detailed notices give class, peak time, active region and activity ID; GOES threshold notices are stored as ">=M5.0"-type classes and de-duplicated against detailed notices of the same flare. Rate-limit and network errors never trigger the fallback.
- Per-feed status now reports the endpoint used; the interface marks "FLR via notifications".
- Tests: 78 backend (fallback parsing, LIVE via fallback, no fallback on 429, fallback failure).

## 1.0.1 — 2026-11-14
Initial prototype.
- Backend: FastAPI + SQLite, normalized telemetry ingest with validation, configurable rules with hysteresis, per-instance alert state machine (ACK / SILENCE / countermeasure / verified CLEAR), SENSOR_FAULT and DATA_STALE detection, R.I.D.G.E. correlation, mission simulator (NOMINAL, HIGH CO2, SOLAR FLARE, TACHYCARDIA, SENSOR FAILURE), Earth sync queue with simulated loss of signal, PVT and private self-check, REST API v1 and `GET /api/state`.
- NASA DONKI (FLR, SEP) integration with 15-minute SQLite cache and LIVE / CACHED_OFFLINE / OFFLINE_BASELINE tiers; OSDR references.
- Frontend: 1920x1080 avionics interface, Master Caution / Warning annunciators, Digital Human Twin, countermeasure guide, radiation and space-weather panel, cabin environment, mission log, simulator, voice and tones, PWA offline shell, IndexedDB snapshot and outbox.
- Tests: 74 backend, 15 frontend, 1 end-to-end demo walkthrough.
