# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS Recovery Monitor - post-session heart-rate recovery (DEMONSTRATION criteria).

Pure function, no database. Statuses:
  RECOVERING       - observation running (first 60 s, or still above baseline inside the window)
  RECOVERED        - heart rate back within baseline + tolerance and the 60-s drop meets the criterion
  REVIEW           - slow drop in the first 60 s after an elevated response, or not back to
                     baseline within the observation window -> medical review
  DATA_INCOMPLETE  - no biosensor, or heart-rate data missing when it is needed. Never treated as normal.

RECOVERED is not a medical clearance; it only means no recovery flag was raised.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.cfms.config import RecoveryCriteria

RECOVERING, RECOVERED, REVIEW, DATA_INCOMPLETE = "RECOVERING", "RECOVERED", "REVIEW", "DATA_INCOMPLETE"
NOTE = ("DEMONSTRATION criteria, not a validated clinical assessment. RECOVERED only means that no recovery flag "
        "was raised; it does not authorize the next session.")


def _hr_at(samples: list[tuple[datetime, float]], t: datetime, max_age_s: float) -> float | None:
    """Last sample at or before t that is not older than max_age_s."""
    best = None
    for ts, v in samples:
        if ts > t:
            break
        if (t - ts).total_seconds() <= max_age_s:
            best = v
    return best


def evaluate_recovery(*, monitored: bool, pre_hr: float | None, end_hr: float | None, peak_hr: float | None,
                      ended_at: datetime, now: datetime, samples: list[tuple[datetime, float]], stale_after_s: float,
                      c: RecoveryCriteria) -> dict[str, Any]:
    window_s = c.window_min * 60.0
    elapsed = max(0.0, (now - ended_at).total_seconds())
    samples = sorted((ts, v) for ts, v in samples if ended_at <= ts <= ended_at + timedelta(seconds=window_s))
    out: dict[str, Any] = {
        "status": RECOVERING, "final": False, "summary": "", "baseline_hr": pre_hr, "end_hr": end_hr, "peak_hr": peak_hr,
        "hrr60": None, "hrr120": None, "time_to_baseline_s": None, "elapsed_s": round(min(elapsed, window_s), 1),
        "window_s": window_s, "threshold_hr": None, "provenance": "DEMONSTRATION", "note": NOTE,
        "criteria": {"window_min": c.window_min, "hrr60_min_bpm": c.hrr60_min_bpm,
                     "baseline_tolerance_bpm": c.baseline_tolerance_bpm, "elevated_response_bpm": c.elevated_response_bpm},
    }

    def done(status: str, summary: str, final: bool = True) -> dict[str, Any]:
        out.update(status=status, summary=summary, final=final)
        return out

    if not monitored:
        return done(DATA_INCOMPLETE, "No biosensor data stream for this crew member - recovery cannot be assessed")
    if pre_hr is None or end_hr is None:
        return done(DATA_INCOMPLETE, "Heart rate at session start or end was not available")

    threshold = pre_hr + c.baseline_tolerance_bpm
    out["threshold_hr"] = threshold
    elevated = end_hr - pre_hr >= c.elevated_response_bpm
    back = next((ts for ts, v in samples if v <= threshold), None)
    if back is not None:
        out["time_to_baseline_s"] = round((back - ended_at).total_seconds(), 1)
    observed_until = min(now, ended_at + timedelta(seconds=window_s))
    current = _hr_at(samples, observed_until, stale_after_s)
    if elapsed >= 60:
        hr60 = _hr_at(samples, ended_at + timedelta(seconds=60), stale_after_s)
        out["hrr60"] = round(end_hr - hr60, 1) if hr60 is not None else None
    if elapsed >= 120:
        hr120 = _hr_at(samples, ended_at + timedelta(seconds=120), stale_after_s)
        out["hrr120"] = round(end_hr - hr120, 1) if hr120 is not None else None

    if elapsed < 60:
        if current is None and elapsed > stale_after_s:
            return done(DATA_INCOMPLETE, "No current heart-rate data during recovery - not treated as normal", final=False)
        return done(RECOVERING, "Observing heart-rate recovery (first 60 s)", final=False)
    if out["hrr60"] is None:
        return done(DATA_INCOMPLETE, "No heart-rate data at +60 s after the session - recovery cannot be assessed")
    if elevated and out["hrr60"] < c.hrr60_min_bpm:
        return done(REVIEW, f"Heart-rate drop in the first 60 s was {out['hrr60']:.0f} bpm, below the DEMONSTRATION "
                            f"criterion of {c.hrr60_min_bpm:.0f} bpm - medical review recommended")
    if back is not None:
        return done(RECOVERED, f"Back within baseline + {c.baseline_tolerance_bpm:.0f} bpm after "
                               f"{out['time_to_baseline_s']:.0f} s; 60-s drop {out['hrr60']:.0f} bpm")
    if elapsed >= window_s:
        if current is None:
            return done(DATA_INCOMPLETE, "No heart-rate data at the end of the observation window")
        return done(REVIEW, f"Not back within baseline + {c.baseline_tolerance_bpm:.0f} bpm within "
                            f"{c.window_min:.0f} min - medical review recommended")
    if current is None:
        return done(DATA_INCOMPLETE, "No current heart-rate data during recovery - not treated as normal", final=False)
    return done(RECOVERING, f"Heart rate {current:.0f} bpm, above baseline + {c.baseline_tolerance_bpm:.0f} bpm", final=False)
