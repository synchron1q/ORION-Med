# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS REST API (/api/v1/fitness). Returns 404 while ORION_CFMS_ENABLED is not set."""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import get_core
from app.cfms.config import met_to_utc
from app.cfms.schemas import ActivityIn, ClearanceIn, EquipmentIn, ReasonIn
from app.cfms.service import CfmsConflict, FitnessService
from app.services.core import HevCore, NotFoundError

router = APIRouter(prefix="/api/v1/fitness", tags=["fitness (CFMS)"])
DISABLED = "CFMS is disabled. Set ORION_CFMS_ENABLED=true to enable the Crew Fitness Management System."


def get_fitness(core: HevCore = Depends(get_core)) -> FitnessService:
    if core.fitness is None:
        raise HTTPException(404, DISABLED)
    return core.fitness


def _guard(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except CfmsConflict as exc:
        raise HTTPException(409, {"message": str(exc), **exc.detail}) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/status", summary="Compact CFMS state (same block as /api/state.fitness).")
def status(core: HevCore = Depends(get_core), f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return f.summary({"alerts": core.list_alerts(), "parameters": core.parameter_states()})


@router.get("/config", summary="DEMONSTRATION program, SIMULATED equipment and policy.")
def config(f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    c = f.cfg
    return {
        "provenance": c.provenance,
        "policy": c.policy.__dict__,
        "forbidden_phase_types": sorted(c.forbidden_phase_types),
        "activity_rules": {k: v.__dict__ for k, v in c.activity_rules.items()},
        "exercise_types": {k: {"label": v.label, "duration_min": v.duration_min, "device_classes": list(v.device_classes),
                               "profile_id": v.profile_id} for k, v in c.exercise_types.items()},
        "program": [p.__dict__ for p in c.program],
        "profiles": {k: {"label": v.label, "heart_rate_pct_hrmax": v.heart_rate_pct, "spo2": v.spo2, "reference": v.reference,
                         "provenance": "DEMONSTRATION"} for k, v in c.profiles.items()},
        "crew_profiles": {k: {**v, "provenance": "SIMULATED"} for k, v in c.crew_profiles.items()},
        "exercise_alarm_policy": c.exercise_alarm_policy,
        "exercise_hr_alarm_pct_hrmax": c.exercise_hr_alarm_pct,
        "required_parameters": list(c.required_parameters),
        "required_cabin_parameters": list(c.required_cabin_parameters),
        "clearance_max_validity_h": c.clearance_max_validity_h,
        "recovery": {**c.recovery.__dict__, "provenance": "DEMONSTRATION"},
        "clearance_issuer_label": c.clearance_issuer_label,
    }


@router.get("/schedule")
def schedule(crew_id: str | None = None, f: FitnessService = Depends(get_fitness)) -> list[dict[str, Any]]:
    return f.schedule(crew_id)


@router.get("/sessions/{session_id}")
def session(session_id: str, f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return _guard(f.session_detail, session_id)


@router.post("/sessions/{session_id}/start", summary="Crew confirms the start. Refused unless the Safety Gate is READY PER PLAN.")
def start(session_id: str, f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return _guard(f.start_session, session_id)


@router.post("/sessions/{session_id}/complete")
def complete(session_id: str, f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return _guard(f.complete_session, session_id)


@router.post("/sessions/{session_id}/abort")
def abort(session_id: str, body: ReasonIn, f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return _guard(f.abort_session, session_id, body.reason)


@router.post("/sessions/{session_id}/request-earliest", summary="Crew request: earliest valid window from now (same MET day).")
def request_earliest(session_id: str, f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return _guard(f.request_earliest, session_id)


@router.get("/recovery", summary="Recovery Monitor: post-session heart-rate recovery (DEMONSTRATION criteria).")
def recovery(limit: int = Query(12, ge=1, le=50), f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return f.recovery_view(limit)


@router.get("/plan", summary="Mission Plan view: YAML baseline + SQLite runtime additions, with origin labels.")
def plan(f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return f.plan_view()


@router.post("/plan/activities", summary="Add an unplanned runtime activity (the baseline YAML is never modified).")
def add_activity(body: ActivityIn, core: HevCore = Depends(get_core), f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    if body.start_met_h is not None:
        start = met_to_utc(f.met_start, body.start_met_h)
    elif body.start_utc is not None:
        start = body.start_utc
    else:
        start = core.now() + timedelta(minutes=body.start_in_min or 0)
    return _guard(f.add_activity, activity_type=body.activity_type, title=body.title, crew=body.crew, start=start,
                  duration_min=body.duration_min, device_id=body.device_id, source=body.source, note=body.note)


@router.delete("/plan/activities/{activity_id}")
def cancel_activity(activity_id: str, f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return _guard(f.cancel_activity, activity_id)


@router.get("/decisions", summary="Planner decision history (original window, conflict, reason, new window).")
def decisions(session_id: str | None = None, limit: int = Query(100, ge=1, le=1000),
              f: FitnessService = Depends(get_fitness)) -> list[dict[str, Any]]:
    return f.decisions(session_id, limit)


@router.post("/replan", summary="Run the deterministic planner now (idempotent).")
def replan(f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return f.replan("MANUAL_REPLAN")


@router.get("/equipment")
def equipment(f: FitnessService = Depends(get_fitness)) -> list[dict[str, Any]]:
    return f.equipment()


@router.post("/equipment/{device_id}", summary="Set the status of a SIMULATED device.")
def set_equipment(device_id: str, body: EquipmentIn, f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return _guard(f.set_equipment, device_id, body.status, body.note, body.source)


@router.get("/clearances")
def clearances(include_inactive: bool = False, f: FitnessService = Depends(get_fitness)) -> list[dict[str, Any]]:
    return f.clearances(include_inactive)


@router.post("/clearances", summary="Record a scoped Medical Clearance (SIMULATED record).")
def grant(body: ClearanceIn, core: HevCore = Depends(get_core), f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    vf = body.valid_from or core.now()
    vu = body.valid_until or (vf + timedelta(hours=body.valid_hours or 0))
    return _guard(f.grant_clearance, crew_id=body.crew_id, exercise_type=body.exercise_type, valid_from=vf, valid_until=vu,
                  issued_by=body.issued_by, note=body.note)


@router.post("/clearances/{clearance_id}/revoke")
def revoke(clearance_id: str, body: ReasonIn, f: FitnessService = Depends(get_fitness)) -> dict[str, Any]:
    return _guard(f.revoke_clearance, clearance_id, body.reason)
