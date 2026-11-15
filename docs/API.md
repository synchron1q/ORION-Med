# REST API

Interactive OpenAPI documentation: `http://localhost:8000/docs`. All timestamps are UTC ISO-8601.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/state` | Complete system state for the UI (parameters, alerts, events since `?since=`, radiation, sync, timeline, `nasa_donki`, `space_weather_simulation`) |
| GET | `/api/v1/health` | Liveness, version, mode |
| GET | `/api/v1/mission` · `/api/v1/crew` | Mission, mission elapsed time, crew |
| GET | `/api/v1/parameters` | Parameter registry with demonstration thresholds and provenance |
| GET | `/api/v1/telemetry?parameter=&since=&limit=` | Telemetry history |
| GET | `/api/v1/telemetry/latest` | Latest state per parameter (OK / STALE / SENSOR_FAULT / NO_DATA / NOT_INSTRUMENTED) |
| POST | `/api/v1/telemetry` | Ingest one record or `{"records": [...]}` (max 500) |
| GET | `/api/v1/alerts?include_cleared=` | Alerts |
| GET | `/api/v1/alerts/{id}` | Alert with full history |
| POST | `/api/v1/alerts/{id}/ack` | Acknowledge (silences audio, never clears) |
| POST | `/api/v1/alerts/{id}/silence` | Silence audio only |
| POST | `/api/v1/alerts/{id}/countermeasure` | Confirm a step `{"step_index": n}` |
| POST | `/api/v1/alerts/{id}/resolve` | CLEAR (409 unless resolution verified) |
| POST | `/api/v1/alerts/silence-all` | Master annunciator press |
| GET | `/api/v1/protocols` · `/api/v1/protocols/{id}` | Countermeasure guides |
| GET | `/api/v1/radiation` · `/api/v1/environment` | Radiation summary, cabin environment |
| GET / POST | `/api/v1/space-weather` · `/api/v1/space-weather/refresh` | DONKI context, manual refresh (max 1/min) |
| GET | `/api/v1/readiness` | EVA readiness gates and triage focus (also included in `/api/state` as `readiness`) |
| GET | `/api/v1/references` | NASA standards, APIs, OSDR datasets |
| GET / POST | `/api/v1/pvt/history` · `/api/v1/pvt/results` | PVT |
| GET / POST | `/api/v1/psych/assessments` | Private self-check |
| GET | `/api/v1/mission/sync-status` | Earth link, queue, last successful sync |
| GET | `/api/v1/events` | Mission event log |
| GET / POST | `/api/v1/simulator` · `/api/v1/simulator/{scenario}` | Scenarios: `nominal`, `high_co2`, `solar_flare`, `tachycardia`, `hypoxia`, `sensor_failure` |
| POST | `/api/v1/simulator/link` · `/api/v1/simulator/control` | Simulate loss of signal; start/stop simulator |

Telemetry record example:
```json
{"parameter": "heart_rate", "value": 78, "unit": "bpm", "timestamp": "2026-11-14T12:00:00Z", "source": "SENSOR", "quality": "GOOD"}
```
`quality: "FAULT"` (value may be null) raises SENSOR_FAULT. Values outside the plausible range are stored as `INVALID` and also raise SENSOR_FAULT.

## CFMS (`/api/v1/fitness`, optional)

Available only with `ORION_CFMS_ENABLED=true` (otherwise 404). Endpoints and examples: [CFMS.md](CFMS.md#api-apiv1fitness).
`GET /api/state` contains `fitness` (`{"enabled": false}` when the module is off).
