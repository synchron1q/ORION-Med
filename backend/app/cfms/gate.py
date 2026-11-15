# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS Safety Gate and in-session exercise monitoring profile.

The gate never authorizes load. Outcomes:
  BLOCKED             - a blocker exists. A Medical Clearance can NEVER override it
                        (active critical medical alerts, forbidden mission phases,
                        plan conflicts and equipment limits).
  CLEARANCE_REQUIRED  - data is incomplete or a medical review is needed (e.g. no
                        biosensor). Incomplete data is never treated as normal.
  READY_PER_PLAN      - no blocker found by the DEMONSTRATION rules; the session
                        fits the plan. The crew still confirms the start.

The exercise profile is a separate DEMONSTRATION monitoring profile. It is for
display and mission-log context only: it never changes global HEV-1 limits and
never suppresses MASTER CAUTION / MASTER WARNING.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.cfms.config import ExerciseProfile

BLOCKED, CLEARANCE_REQUIRED, READY = "BLOCKED", "CLEARANCE_REQUIRED", "READY_PER_PLAN"
GATE_DISCLAIMER = ("Decision support only (DEMONSTRATION rules). READY PER PLAN means no blocker was found; "
                   "it is not a medical authorization. The crew and the medical officer decide.")
PROFILE_NOTE = ("DEMONSTRATION in-session profile for display and logging only. Global HEV-1 alert limits are "
                "unchanged and MASTER CAUTION / MASTER WARNING are never suppressed.")
CABIN_CATEGORIES = ("environmental", "radiation")
DATA_KINDS = ("SENSOR_FAULT", "DATA_STALE")


@dataclass(frozen=True)
class ClearanceView:
    id: str
    crew_id: str
    exercise_type: str
    valid_from: datetime
    valid_until: datetime
    revoked: bool
    issued_by: str
    issued_at: datetime | None = None

    def covers(self, crew_id: str, exercise_type: str, start: datetime, end: datetime) -> bool:
        return (not self.revoked and self.crew_id == crew_id and self.exercise_type == exercise_type
                and self.valid_from <= start and end <= self.valid_until)


def _reason(level: str, code: str, text: str, ref: str | None = None) -> dict[str, Any]:
    return {"level": level, "code": code, "text": text, "ref": ref}


def _alert_scope(alert: dict[str, Any], categories: dict[str, str]) -> str:
    """'cabin' (affects every crew member) or 'crew' (the monitored crew member)."""
    cat = categories.get(alert.get("parameter") or "")
    if cat in CABIN_CATEGORIES or (cat is None and alert.get("zone") == "radiation"):
        return "cabin"
    return "crew"


def evaluate_gate(*, crew_id: str, monitored_crew_id: str | None, exercise_type: str, start: datetime, end: datetime,
                  alerts: list[dict[str, Any]], parameters: list[dict[str, Any]], required_parameters: tuple[str, ...],
                  required_cabin_parameters: tuple[str, ...] = (), plan_conflict: Any = None, device_id: str | None = None, device_label: str | None = None,
                  device_status: str | None = None, clearances: list[ClearanceView] = (),
                  extra: list[dict[str, Any]] = ()) -> dict[str, Any]:
    reasons: list[dict[str, Any]] = []
    categories = {p["id"]: p.get("category") for p in parameters}
    monitored = crew_id == monitored_crew_id

    # Plan and equipment limits.
    if plan_conflict is not None:
        reasons.append(_reason("BLOCK", f"PLAN_{plan_conflict.code}", plan_conflict.text, plan_conflict.ref))
    if device_id is None:
        reasons.append(_reason("BLOCK", "NO_DEVICE", "No exercise device assigned"))
    elif device_status != "OPERATIONAL":
        reasons.append(_reason("BLOCK", "EQUIPMENT", f"{device_label or device_id} status {device_status}", device_id))

    # Active alerts (lifecycle ACTIVE or RECOVERY; cleared alerts are not passed in).
    for a in alerts:
        scope = _alert_scope(a, categories)
        applies = scope == "cabin" or monitored
        if not applies:
            if a["severity"] == "WARNING" and a["kind"] not in DATA_KINDS:
                reasons.append(_reason("BLOCK", "MASTER_WARNING", f"MASTER WARNING active: {a['title']}", a["id"]))
            continue
        if a["kind"] in DATA_KINDS:
            reasons.append(_reason("CLEARANCE", "DATA_INCOMPLETE", f"{a['title']} ({a['kind'].replace('_', ' ')})", a["id"]))
        elif a["severity"] == "WARNING":
            reasons.append(_reason("BLOCK", "MASTER_WARNING", f"MASTER WARNING active: {a['title']}", a["id"]))
        elif a["severity"] == "CAUTION":
            reasons.append(_reason("BLOCK", "MEDICAL_CAUTION" if scope == "crew" else "CABIN_CAUTION",
                                   f"MASTER CAUTION active: {a['title']}", a["id"]))
        elif a["severity"] == "ADVISORY":
            reasons.append(_reason("CLEARANCE", "ADVISORY", f"Advisory active: {a['title']}", a["id"]))

    # Cabin atmosphere must be monitored for everyone; a clearance cannot cover it.
    by_id = {p["id"]: p for p in parameters}
    for pid in required_cabin_parameters:
        p = by_id.get(pid)
        status = p.get("status") if p else "NOT_CONFIGURED"
        if status != "OK":
            label = p.get("label", pid) if p else pid
            reasons.append(_reason("BLOCK", "CABIN_DATA_INCOMPLETE", f"{label}: {status.replace('_', ' ')} - cabin atmosphere not monitored", pid))

    # Physiological data availability.
    if monitored:
        for pid in required_parameters:
            p = by_id.get(pid)
            status = p.get("status") if p else "NOT_CONFIGURED"
            if status != "OK":
                label = p.get("label", pid) if p else pid
                reasons.append(_reason("CLEARANCE", "DATA_INCOMPLETE", f"{label}: {status.replace('_', ' ')}", pid))
    else:
        reasons.append(_reason("CLEARANCE", "NO_BIOSENSOR",
                               f"No biosensor data stream for {crew_id} in this prototype - physiological status unknown"))
    reasons.extend(extra)

    blocked = any(r["level"] == "BLOCK" for r in reasons)
    needs = any(r["level"] == "CLEARANCE" for r in reasons)
    match = next((c for c in clearances if c.covers(crew_id, exercise_type, start, end)), None)
    if blocked:
        status = BLOCKED
        if match:
            reasons.append(_reason("INFO", "CLEARANCE_NOT_APPLICABLE",
                                   "A Medical Clearance exists but cannot override a blocker", match.id))
    elif needs and match is None:
        status = CLEARANCE_REQUIRED
    else:
        status = READY
    return {
        "status": status,
        "reasons": reasons,
        "clearance": ({"id": match.id, "issued_by": match.issued_by, "valid_until": match.valid_until.isoformat()}
                      if match and not blocked and needs else None),
        "evaluated_window": [start.isoformat(), end.isoformat()],
        "disclaimer": GATE_DISCLAIMER,
    }


BAND_ORDER = ("IN_TARGET", "BELOW_TARGET", "ABOVE_TARGET", "REVIEW", "DATA_INCOMPLETE", "STOP_RECOMMENDED")


def evaluate_profile(profile: ExerciseProfile, parameters: list[dict[str, Any]], monitored: bool,
                     hrmax: float | None = None, alarm_note: str | None = None) -> dict[str, Any]:
    """DEMONSTRATION in-session band for the monitored crew member (limits in % of individual HRmax)."""
    by_id = {p["id"]: p for p in parameters}
    h = profile.heart_rate_bpm(hrmax)
    out: dict[str, Any] = {"profile_id": profile.id, "label": profile.label, "provenance": "DEMONSTRATION",
                           "limits": {"heart_rate": h, "heart_rate_pct_hrmax": profile.heart_rate_pct, "spo2": profile.spo2},
                           "hrmax_bpm": hrmax, "reference": profile.reference, "note": alarm_note or PROFILE_NOTE}
    if not monitored:
        out.update(heart_rate=None, spo2=None, overall="DATA_INCOMPLETE",
                   summary="No biosensor data stream for this crew member - in-session monitoring unavailable")
        return out

    def val(pid: str) -> float | None:
        p = by_id.get(pid)
        return p.get("value") if p and p.get("status") == "OK" else None

    hr, spo2 = val("heart_rate"), val("spo2")
    if hr is None or not h:
        hr_band = "DATA_INCOMPLETE"
    elif hr > h.get("stop_above", 1e9):
        hr_band = "STOP_RECOMMENDED"
    elif hr > h.get("review_above", 1e9):
        hr_band = "REVIEW"
    elif hr > h.get("target_high", 1e9):
        hr_band = "ABOVE_TARGET"
    elif hr < h.get("target_low", -1e9):
        hr_band = "BELOW_TARGET"
    else:
        hr_band = "IN_TARGET"
    o = profile.spo2
    if spo2 is None:
        spo2_band = "DATA_INCOMPLETE"
    elif spo2 < o.get("stop_below", -1e9):
        spo2_band = "STOP_RECOMMENDED"
    elif spo2 < o.get("review_below", -1e9):
        spo2_band = "REVIEW"
    else:
        spo2_band = "IN_TARGET"
    overall = max(hr_band, spo2_band, key=BAND_ORDER.index)
    text = {
        "IN_TARGET": "Within the DEMONSTRATION target zone",
        "BELOW_TARGET": "Heart rate below the DEMONSTRATION target zone",
        "ABOVE_TARGET": "Heart rate above the DEMONSTRATION target zone",
        "REVIEW": "Crew review recommended (DEMONSTRATION profile limit exceeded)",
        "DATA_INCOMPLETE": "In-session data incomplete - not treated as normal",
        "STOP_RECOMMENDED": "STOP EXERCISE RECOMMENDED (DEMONSTRATION profile limit exceeded)",
    }[overall]
    pct = round(hr * 100.0 / hrmax) if hr is not None and hrmax else None
    out.update(heart_rate={"value": hr, "band": hr_band, "pct_hrmax": pct}, spo2={"value": spo2, "band": spo2_band}, overall=overall, summary=text)
    return out
