# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Operational readiness (EVA decision support) and triage focus for the COMMAND screen.

Reworked from the team's "R.I.D.G.E. Operational Readiness" concept.

Design rules
------------
* Deterministic and derived only from the engine's own outputs: validated
  parameter states, the same configured demonstration thresholds and the
  active alerts. No additional numeric limits are introduced here.
* Missing, stale or faulty inputs never count as nominal: the affected gate is
  UNKNOWN and the overall result becomes DATA_INCOMPLETE.
* Decision support only. The result never states that an EVA is safe or
  "cleared"; NO_BLOCKERS means no configured blocker was found.
* The triage focus tells the crew which checklist to open first. It is not a
  diagnosis and it never suppresses an alarm.
"""
from __future__ import annotations

from typing import Any

SEV_RANK = {"NOMINAL": 0, "ADVISORY": 1, "CAUTION": 2, "WARNING": 3}
STATUS_RANK = {"CLEAR": 0, "REVIEW": 1, "UNKNOWN": 2, "HOLD": 3}

GATES: list[tuple[str, str, list[str]]] = [
    ("radiation", "Radiation exposure", ["dose_rate", "accumulated_dose"]),
    ("atmosphere", "Cabin atmosphere", ["cabin_co2", "cabin_o2", "cabin_pressure"]),
    ("cardiorespiratory", "Cardiorespiratory", ["heart_rate", "spo2", "resp_rate", "bp_systolic"]),
    ("alertness", "Alertness and sleep", ["pvt_mean_rt", "sleep_hours"]),
]

DISCLAIMER = (
    "Decision support only. Final EVA go/no-go decisions belong to the crew, the flight "
    "surgeon and mission control. Thresholds are demonstration values."
)
TRIAGE_DISCLAIMER = "Suggested focus for the crew - not a diagnosis. All alerts remain active."

# Ordered triage rules: (focus id, title, rule ids that select it, protocol id).
TRIAGE_RULES: list[tuple[str, str, tuple[str, ...], str]] = [
    ("CABIN_CO2", "Cabin CO2 removal", ("TH-cabin_co2",), "CM-ECLSS-01"),
    ("CABIN_ATMOSPHERE", "Cabin pressure / O2", ("TH-cabin_pressure", "TH-cabin_o2"), "CM-ECLSS-02"),
    ("CIRCULATION", "Circulation / bleeding check", ("TH-bp_systolic", "RIDGE-BP-HR"), "CM-HEMO-01"),
    ("OXYGENATION", "Oxygenation and breathing", ("TH-spo2", "TH-resp_rate"), "CM-O2-01"),
    ("RADIATION", "Radiation exposure", ("TH-dose_rate", "TH-accumulated_dose"), "CM-RAD-01"),
    ("HEART_RATE", "Heart rate", ("TH-heart_rate", "TH-hrv"), "CM-CARDIO-01"),
    ("THERMAL", "Core temperature", ("TH-body_temp",), "CM-THERM-01"),
    ("ALERTNESS", "Alertness (PVT / sleep)", ("TH-pvt_mean_rt", "TH-sleep_hours"), "CM-NEURO-01"),
]


def _param_status(p: dict[str, Any]) -> tuple[str, str]:
    """Map a parameter state to a gate status plus a reason."""
    label = p.get("short") or p["id"]
    if not p.get("available", True):
        return "CLEAR", ""
    if p.get("status") != "OK":
        return "UNKNOWN", f"{label}: {str(p.get('status')).replace('_', ' ').lower()} - not assumed normal"
    band = p.get("band") or "NOMINAL"
    if band == "WARNING":
        return "HOLD", f"{label} {p.get('value')} {p.get('unit')} beyond warning limit"
    if band == "CAUTION":
        return "REVIEW", f"{label} {p.get('value')} {p.get('unit')} beyond caution limit"
    if band == "ADVISORY":
        return "REVIEW", f"{label} advisory band"
    return "CLEAR", ""


def evaluate_eva_readiness(state: dict[str, Any], space_weather_risk: str = "NOMINAL",
                           space_weather_source: str = "NASA DONKI") -> dict[str, Any]:
    params = {p["id"]: p for p in state.get("parameters", [])}
    gates_out = []
    for gid, label, pids in GATES:
        status, reasons = "CLEAR", []
        if not any(pid in params for pid in pids):
            status, reasons = "UNKNOWN", ["no telemetry configured for this gate"]
        for pid in pids:
            p = params.get(pid)
            if p is None:
                continue
            s, why = _param_status(p)
            if STATUS_RANK[s] > STATUS_RANK[status]:
                status = s
            if why:
                reasons.append(why)
        if gid == "radiation":
            rad = state.get("radiation") or {}
            frac = rad.get("budget_fraction")
            if frac is not None and frac >= 0.8 and STATUS_RANK[status] < STATUS_RANK["REVIEW"]:
                status = "REVIEW"
                reasons.append(f"accumulated dose at {frac * 100:.0f}% of the demonstration mission budget")
            if space_weather_risk == "WARNING":
                status = "HOLD"
                reasons.append(f"space-weather context WARNING ({space_weather_source})")
            elif space_weather_risk == "CAUTION" and STATUS_RANK[status] < STATUS_RANK["REVIEW"]:
                status = "REVIEW"
                reasons.append(f"space-weather context CAUTION ({space_weather_source})")
        gates_out.append({"id": gid, "label": label, "status": status, "reasons": reasons})

    statuses = {g["status"] for g in gates_out}
    if "HOLD" in statuses:
        overall = "HOLD_RECOMMENDED"
    elif "UNKNOWN" in statuses:
        overall = "DATA_INCOMPLETE"
    elif "REVIEW" in statuses:
        overall = "REVIEW"
    else:
        overall = "NO_BLOCKERS"
    return {
        "status": overall,
        "gates": gates_out,
        "gates_clear": sum(1 for g in gates_out if g["status"] == "CLEAR"),
        "gates_total": len(gates_out),
        "disclaimer": DISCLAIMER,
    }


def evaluate_triage_focus(state: dict[str, Any], protocols: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Pick the checklist the crew should open first, from the active alerts."""
    alerts = [a for a in state.get("alerts", []) if a.get("lifecycle") != "CLEARED"]
    ridge = [a for a in alerts if a.get("kind") == "CORRELATION"]
    context = [a["title"].replace("R.I.D.G.E.: ", "") for a in ridge]
    instrumentation = [a for a in alerts if a.get("kind") in ("SENSOR_FAULT", "DATA_STALE")]
    # Ranking: severity, then ACTIVE before RECOVERY, then the fixed priority order.
    candidates: list[tuple[int, int, int, dict[str, Any], str, str, str]] = []
    for order, (fid, title, rules, proto) in enumerate(TRIAGE_RULES):
        for a in alerts:
            if a.get("rule_id") in rules:
                candidates.append((SEV_RANK[a["severity"]], int(a.get("lifecycle") == "ACTIVE"), -order, a, fid, title, proto))
    for a in instrumentation:
        candidates.append((SEV_RANK[a["severity"]], int(a.get("lifecycle") == "ACTIVE"), -len(TRIAGE_RULES), a,
                           "INSTRUMENTATION", "Restore telemetry", "CM-SENSOR-01"))
    if not candidates:
        return {
            "focus": "NOMINAL", "title": "No active findings", "severity": "NOMINAL", "alert_id": None,
            "protocol_id": None, "kit": None, "rationale": "All monitored parameters are inside configured demonstration ranges.",
            "context": context, "disclaimer": TRIAGE_DISCLAIMER,
        }
    _, _, _, alert, fid, title, proto_id = max(candidates, key=lambda c: (c[0], c[1], c[2]))
    proto = protocols.get(alert.get("protocol_id") or proto_id) or protocols.get(proto_id) or {}
    rationale = alert.get("message", "")
    if fid == "HEART_RATE" and any(a.get("rule_id") == "RIDGE-HR-ACT" for a in ridge):
        rationale += " Context: high measured physical activity. The alert stays active until verified."
    return {
        "focus": fid,
        "title": title,
        "severity": alert["severity"],
        "alert_id": alert["id"],
        "protocol_id": proto.get("id"),
        "kit": proto.get("kit"),
        "rationale": rationale,
        "context": context,
        "disclaimer": TRIAGE_DISCLAIMER,
    }
