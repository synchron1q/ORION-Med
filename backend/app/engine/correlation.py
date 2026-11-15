# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""R.I.D.G.E. - deterministic correlation and context layer.

R.I.D.G.E. relates the human state to the spacecraft environment, the
space-weather context and mission operations. Rules are configured in
config/demo_thresholds.yaml. A finding means "these observations happened
close together in time". It is never presented as a cause or a diagnosis.
"""
from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.engine.rules import Severity

OPS = {">=": operator.ge, ">": operator.gt, "<=": operator.le, "<": operator.lt}

UNCERTAINTY = (
    "Correlation is not proof of causation. This finding only reports that the "
    "listed observations occurred within the configured time window. Original "
    "measurements are preserved unchanged."
)


@dataclass(frozen=True)
class Observation:
    """Most recent time a parameter met a level, plus the value at that time."""

    value: float
    severity: Severity
    timestamp: datetime


@dataclass
class Finding:
    rule_id: str
    title: str
    explanation: str
    factors: list[dict[str, Any]]
    uncertainty: str = UNCERTAINTY


def _match(cond: dict[str, Any], history: dict[str, list[Observation]], swx: list[datetime], now: datetime, window_s: float) -> dict[str, Any] | None:
    if "space_weather_within_s" in cond:
        limit = float(cond["space_weather_within_s"])
        recent = [t for t in swx if 0 <= (now - t).total_seconds() <= limit]
        if not recent:
            return None
        t = max(recent)
        return {"factor": "space_weather_event", "timestamp": t.isoformat(), "detail": "Space-weather event reported (context only)"}
    pid = cond["parameter"]
    for obs in sorted(history.get(pid, []), key=lambda o: o.timestamp, reverse=True):
        if (now - obs.timestamp).total_seconds() > window_s:
            break
        ok = False
        if "min_severity" in cond:
            ok = obs.severity >= Severity[cond["min_severity"]]
        elif "op" in cond:
            ok = OPS[cond["op"]](obs.value, float(cond["value"]))
        if ok:
            return {
                "factor": pid,
                "value": obs.value,
                "severity": obs.severity.name,
                "timestamp": obs.timestamp.isoformat(),
            }
    return None


def evaluate_rules(
    rules: list[dict[str, Any]],
    history: dict[str, list[Observation]],
    space_weather_times: list[datetime],
    now: datetime,
) -> tuple[list[Finding], set[str]]:
    """Return (active findings, ids of rules that are currently not satisfied).

    The newest observation of every condition parameter must also still be
    current: a rule is satisfied only if its *primary* conditions are met by
    the latest valid observation of that parameter.
    """
    findings: list[Finding] = []
    inactive: set[str] = set()
    for rule in rules:
        window = float(rule.get("window_s", 600))
        factors: list[dict[str, Any]] = []
        ok = True
        for i, cond in enumerate(rule.get("conditions") or []):
            if i == 0 and "parameter" in cond:
                latest = max(history.get(cond["parameter"], []), key=lambda o: o.timestamp, default=None)
                if latest is None or not _match(cond, {cond["parameter"]: [latest]}, space_weather_times, now, window):
                    ok = False
                    break
            m = _match(cond, history, space_weather_times, now, window)
            if m is None:
                ok = False
                break
            factors.append(m)
        if ok and rule.get("any_of"):
            hits = [m for c in rule["any_of"] if (m := _match(c, history, space_weather_times, now, window))]
            if not hits:
                ok = False
            factors += hits
        if ok:
            findings.append(Finding(rule["id"], rule.get("title", rule["id"]), rule.get("explanation", ""), factors))
        else:
            inactive.add(rule["id"])
    return findings, inactive
