# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Versioned REST API (/api/v1)."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.api.deps import get_core, get_db
from app.core.settings import APP_VERSION
from app.engine.alert_machine import TransitionError
from app.integrations import nasa_donki
from app.models import TelemetryRecord
from app.schemas.api import (
    AlertOut, CountermeasureIn, IngestResult, LinkIn, PsychIn, PVTIn, SimulatorControlIn, TelemetryBatchIn,
    TelemetryIn, TelemetryRecordOut,
)
from app.services.core import HevCore, IngestError, NotFoundError, TelemetryInput, iso

router = APIRouter(prefix="/api/v1")


def _guard(fn, *args):
    try:
        return fn(*args)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except TransitionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (IngestError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/health", tags=["system"])
def health(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return {"status": "OK", "version": APP_VERSION, "server_time": iso(core.now()), "mission_id": core.mission_id,
            "simulator_enabled": core.simulator.enabled, "demo_mode": core.settings.demo_mode,
            "cfms_enabled": core.fitness is not None}


@router.get("/mission", tags=["mission"])
def mission(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.mission_info()


@router.get("/crew", tags=["mission"])
def crew(core: HevCore = Depends(get_core)) -> list[dict[str, Any]]:
    return core.mission_info()["crew"]


@router.get("/parameters", tags=["telemetry"])
def parameters(core: HevCore = Depends(get_core)) -> list[dict[str, Any]]:
    return [p.to_public() for p in core.reg.parameters.values()]


@router.get("/telemetry", response_model=list[TelemetryRecordOut], tags=["telemetry"])
def telemetry(parameter: str | None = None, since: datetime | None = None, limit: int = Query(200, ge=1, le=2000),
              db: Session = Depends(get_db)) -> list[dict[str, Any]]:
    q = select(TelemetryRecord)
    if parameter:
        q = q.where(TelemetryRecord.parameter == parameter)
    if since:
        q = q.where(TelemetryRecord.timestamp >= since)
    rows = db.scalars(q.order_by(desc(TelemetryRecord.timestamp)).limit(limit)).all()
    return [{"id": r.id, "parameter": r.parameter, "category": r.category, "value": r.value, "unit": r.unit,
             "timestamp": iso(r.timestamp), "source": r.source, "quality": r.quality, "mission_id": r.mission_id,
             "crew_id": r.crew_id, "metadata": r.meta} for r in rows]


@router.get("/telemetry/latest", tags=["telemetry"])
def telemetry_latest(core: HevCore = Depends(get_core)) -> list[dict[str, Any]]:
    return core.parameter_states()


@router.post("/telemetry", response_model=IngestResult, tags=["telemetry"])
def post_telemetry(body: TelemetryIn | TelemetryBatchIn, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    records = body.records if isinstance(body, TelemetryBatchIn) else [body]
    items = [TelemetryInput(r.parameter, r.value, r.unit, r.timestamp, r.source, r.quality, r.crew_id, r.metadata) for r in records]
    result = core.ingest(items)
    if result["accepted"] == 0:
        raise HTTPException(422, {"message": "No telemetry accepted", **result})
    return result


@router.get("/alerts", response_model=list[AlertOut], tags=["alerts"])
def alerts(include_cleared: bool = False, limit: int = Query(100, ge=1, le=500), core: HevCore = Depends(get_core)) -> list[dict[str, Any]]:
    return core.list_alerts(include_cleared=include_cleared, limit=limit)


@router.post("/alerts/silence-all", tags=["alerts"])
def silence_all(core: HevCore = Depends(get_core)) -> dict[str, int]:
    return {"silenced": core.silence_all()}


@router.get("/alerts/{alert_id}", response_model=AlertOut, tags=["alerts"])
def alert_detail(alert_id: str, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return _guard(core.alert_detail, alert_id)


@router.post("/alerts/{alert_id}/ack", response_model=AlertOut, tags=["alerts"],
             summary="ACK: acknowledge and silence audio. Never clears the alert.")
def ack(alert_id: str, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return _guard(core.acknowledge, alert_id)


@router.post("/alerts/{alert_id}/silence", response_model=AlertOut, tags=["alerts"])
def silence(alert_id: str, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return _guard(core.silence, alert_id)


@router.post("/alerts/{alert_id}/countermeasure", response_model=AlertOut, tags=["alerts"])
def countermeasure(alert_id: str, body: CountermeasureIn, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return _guard(core.confirm_step, alert_id, body.step_index)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut, tags=["alerts"],
             summary="CLEAR: allowed only after verified resolution; archives the alert.")
def resolve(alert_id: str, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return _guard(core.resolve, alert_id)


@router.get("/protocols", tags=["countermeasures"])
def protocols(core: HevCore = Depends(get_core)) -> list[dict[str, Any]]:
    return [p.to_public() for p in core.reg.protocols.values()]


@router.get("/protocols/{protocol_id}", tags=["countermeasures"])
def protocol(protocol_id: str, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    p = core.reg.protocols.get(protocol_id)
    if p is None:
        raise HTTPException(404, f"Protocol {protocol_id} not found")
    return p.to_public()


@router.get("/radiation", tags=["radiation"])
def radiation(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.radiation_summary()


@router.get("/environment", tags=["telemetry"])
def environment(core: HevCore = Depends(get_core)) -> list[dict[str, Any]]:
    return [p for p in core.parameter_states() if p["category"] == "environmental"]


@router.get("/space-weather", tags=["external"])
async def space_weather(db: Session = Depends(get_db), core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return dict(await nasa_donki.get_nasa_donki_context(db, allow_fetch=core.settings.external_fetch_enabled))


@router.post("/space-weather/refresh", tags=["external"])
async def space_weather_refresh(db: Session = Depends(get_db), core: HevCore = Depends(get_core)) -> dict[str, Any]:
    if not core.settings.external_fetch_enabled:
        raise HTTPException(409, "External fetching is disabled (ORION_EXTERNAL_FETCH=false)")
    ok, message = await nasa_donki.request_manual_refresh(db)
    return {"scheduled": ok, "message": message}


@router.get("/readiness", tags=["mission"], summary="EVA decision support and triage focus (deterministic, demonstration thresholds).")
async def readiness(db: Session = Depends(get_db), core: HevCore = Depends(get_core)) -> dict[str, Any]:
    state = await run_in_threadpool(core.dashboard, None)
    swx = await nasa_donki.get_nasa_donki_context(db, allow_fetch=core.settings.external_fetch_enabled)
    return core.readiness(state, dict(swx))


@router.get("/reference-data", tags=["external"], summary="NASA reference values (context only, never an alarm limit).")
def reference_data(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    from app.core.reference_data import load_reference_data
    return load_reference_data(core.settings.config_dir)


@router.get("/references", tags=["external"])
def references(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.osdr.references()


@router.get("/pvt/history", tags=["crew"])
def pvt_history(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.pvt_history()


@router.post("/pvt/results", tags=["crew"])
def pvt_results(body: PVTIn, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return _guard(core.submit_pvt, body.reaction_times_ms, body.misses, body.false_starts, body.duration_s)


@router.get("/psych/assessments", tags=["crew"])
def psych_list(core: HevCore = Depends(get_core)) -> list[dict[str, Any]]:
    return core.psych_history()


@router.post("/psych/assessments", tags=["crew"])
def psych_post(body: PsychIn, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.submit_psych(body.mood, body.stress, body.fatigue, body.sleep_quality, body.notes, body.private)


@router.get("/mission/sync-status", tags=["mission"])
def sync_status(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.sync.status()


@router.get("/events", tags=["mission"])
def events(limit: int = Query(50, ge=1, le=500), core: HevCore = Depends(get_core)) -> list[dict[str, Any]]:
    return core.timeline(limit)


@router.get("/simulator", tags=["simulator"])
def simulator_status(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.simulator.status()


@router.post("/simulator/control", tags=["simulator"])
def simulator_control(body: SimulatorControlIn, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return _guard(core.simulator.set_enabled, body.enabled)


@router.post("/simulator/link", tags=["simulator"], summary="Simulate Earth link loss (LOS) or restore (AOS).")
def simulator_link(body: LinkIn, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.sync.set_link(body.up)


@router.post("/simulator/{scenario}", tags=["simulator"])
async def simulator_scenario(scenario: str, core: HevCore = Depends(get_core)) -> dict[str, Any]:
    if not core.simulator.enabled:
        raise HTTPException(409, "Simulator is disabled")
    return await run_in_threadpool(_guard, core.simulator.set_scenario, scenario.lower())


@router.get("/ksp/status", tags=["ksp"], summary="Get live KSP 1 OrionMedKSP VesselModule telemetry and connection status.")
def ksp_status(core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return core.ksp_status()


@router.post("/ksp/sync", tags=["ksp"], summary="Receive live flight & Kerbal crew telemetry from KSP 1 OrionMedKSP.dll.")
async def ksp_sync(body: dict[str, Any], core: HevCore = Depends(get_core)) -> dict[str, Any]:
    return await run_in_threadpool(core.update_ksp_telemetry, body)
