# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Per-instance alert finite-state machine.

Each alert instance keeps its own state. The state is decomposed into
independent dimensions instead of one global enum:

* severity       - ADVISORY / CAUTION / WARNING (escalates and de-escalates)
* lifecycle      - ACTIVE -> RECOVERY -> CLEARED (RECOVERY can relapse to ACTIVE)
* acknowledged   - crew has seen the alert (ACK silences audio, never clears)
* silenced       - audio muted, visual alert stays
* cm_status      - NONE / AVAILABLE / IN_PROGRESS / COMPLETED
* kind           - THRESHOLD / SENSOR_FAULT / DATA_STALE / CORRELATION

`display_states` maps these dimensions onto the named states of the
specification (WARNING, ACKNOWLEDGED, SILENCED, COUNTERMEASURE_IN_PROGRESS,
RECOVERY, CLEARED, SENSOR_FAULT, DATA_STALE ...).

The functions operate on any object with the attributes listed in
`AlertLike`, so they are used both with ORM rows and with plain dataclasses
in unit tests. Every function returns a list of Transition records that the
caller persists as alert history.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from app.engine.rules import Severity

ACTIVE, RECOVERY, CLEARED = "ACTIVE", "RECOVERY", "CLEARED"
CM_NONE, CM_AVAILABLE, CM_IN_PROGRESS, CM_COMPLETED = "NONE", "AVAILABLE", "IN_PROGRESS", "COMPLETED"
KINDS = ("THRESHOLD", "SENSOR_FAULT", "DATA_STALE", "CORRELATION")


class TransitionError(Exception):
    """Raised when an operator action is not allowed in the current state."""


class AlertLike(Protocol):
    kind: str
    severity: int
    peak_severity: int
    lifecycle: str
    acknowledged: bool
    silenced: bool
    cm_status: str
    cm_steps_done: list
    occurrence_count: int
    recovery_since: datetime | None
    resolution_verified: bool
    cleared_at: datetime | None
    cleared_by: str | None
    updated_at: datetime


@dataclass
class Transition:
    event_type: str
    detail: str = ""
    actor: str = "SYSTEM"


@dataclass
class AlertState:
    """Plain in-memory alert used by unit tests and documentation examples."""

    kind: str = "THRESHOLD"
    severity: int = int(Severity.CAUTION)
    peak_severity: int = int(Severity.CAUTION)
    lifecycle: str = ACTIVE
    acknowledged: bool = False
    silenced: bool = False
    cm_status: str = CM_NONE
    cm_steps_done: list = field(default_factory=list)
    occurrence_count: int = 1
    recovery_since: datetime | None = None
    resolution_verified: bool = False
    cleared_at: datetime | None = None
    cleared_by: str | None = None
    updated_at: datetime | None = None


def init_alert(alert: AlertLike, severity: Severity, now: datetime, has_protocol: bool) -> list[Transition]:
    if severity <= Severity.NOMINAL:
        raise TransitionError("An alert cannot be raised at NOMINAL severity")
    alert.severity = int(severity)
    alert.peak_severity = int(severity)
    alert.lifecycle = ACTIVE
    alert.acknowledged = False
    alert.silenced = False
    alert.cm_status = CM_AVAILABLE if has_protocol else CM_NONE
    alert.cm_steps_done = []
    alert.occurrence_count = 1
    alert.recovery_since = None
    alert.resolution_verified = False
    alert.cleared_at = None
    alert.cleared_by = None
    alert.updated_at = now
    return [Transition("RAISED", f"{Severity(severity).name} raised")]


def on_condition(
    alert: AlertLike,
    severity: Severity,
    now: datetime,
    recovery_hold_s: float,
    auto_clear: bool,
) -> list[Transition]:
    """Feed a new evaluation (from FRESH, VALID data) into the alert."""
    if alert.lifecycle == CLEARED:
        raise TransitionError("Alert is already cleared")
    out: list[Transition] = []
    current = Severity(alert.severity)

    if severity > Severity.NOMINAL:
        if alert.lifecycle == RECOVERY:
            alert.lifecycle = ACTIVE
            alert.recovery_since = None
            alert.resolution_verified = False
            alert.occurrence_count += 1
            alert.acknowledged = False
            alert.silenced = False
            out.append(Transition("RECURRED", f"Condition returned at {severity.name}"))
        if severity > current:
            alert.severity = int(severity)
            alert.peak_severity = max(alert.peak_severity, int(severity))
            alert.acknowledged = False
            alert.silenced = False
            out.append(Transition("ESCALATED", f"{current.name} -> {severity.name}"))
        elif severity < current:
            alert.severity = int(severity)
            out.append(Transition("DEESCALATED", f"{current.name} -> {severity.name}"))
    else:
        if alert.lifecycle == ACTIVE:
            alert.lifecycle = RECOVERY
            alert.recovery_since = now
            alert.resolution_verified = False
            out.append(Transition("RECOVERY_STARTED", "Measurements back inside configured limits"))
        if (
            alert.lifecycle == RECOVERY
            and not alert.resolution_verified
            and alert.recovery_since is not None
            and (now - alert.recovery_since).total_seconds() >= recovery_hold_s
        ):
            alert.resolution_verified = True
            out.append(Transition("RESOLUTION_VERIFIED", f"Nominal for >= {recovery_hold_s:g} s with fresh data"))
            if auto_clear:
                out += clear(alert, now, actor="SYSTEM")
    if out:
        alert.updated_at = now
    return out


def on_hysteresis_band(alert: AlertLike, now: datetime) -> list[Transition]:
    """Value inside limits but not past the hysteresis margin.

    An ACTIVE alert holds. A RECOVERY alert restarts its hold timer and loses
    any verified resolution: recovery must be demonstrated continuously.
    """
    if alert.lifecycle != RECOVERY:
        return []
    out: list[Transition] = []
    if alert.resolution_verified:
        out.append(Transition("RESOLUTION_REVOKED", "Value drifted into the hysteresis band"))
    alert.resolution_verified = False
    alert.recovery_since = now
    alert.updated_at = now
    return out


def acknowledge(alert: AlertLike, now: datetime) -> list[Transition]:
    """ACK: crew has seen the alert. Silences audio. Never resolves or clears."""
    if alert.lifecycle == CLEARED:
        raise TransitionError("Cannot acknowledge a cleared alert")
    if alert.acknowledged:
        return []
    alert.acknowledged = True
    alert.silenced = True
    alert.updated_at = now
    return [Transition("ACKNOWLEDGED", "Crew acknowledged; audio silenced", "CREW")]


def silence(alert: AlertLike, now: datetime) -> list[Transition]:
    """SILENCE: mute audio only. Visual alert stays active."""
    if alert.lifecycle == CLEARED:
        raise TransitionError("Cannot silence a cleared alert")
    if alert.silenced:
        return []
    alert.silenced = True
    alert.updated_at = now
    return [Transition("SILENCED", "Audio silenced; visual alert remains", "CREW")]


def confirm_step(alert: AlertLike, step_index: int, total_steps: int, now: datetime) -> list[Transition]:
    """Record crew confirmation of one countermeasure step.

    Completing all steps does NOT resolve the underlying condition.
    """
    if alert.lifecycle == CLEARED:
        raise TransitionError("Cannot update the countermeasure of a cleared alert")
    if alert.cm_status == CM_NONE or total_steps <= 0:
        raise TransitionError("No countermeasure protocol is configured for this alert")
    if not 0 <= step_index < total_steps:
        raise TransitionError(f"Step index {step_index} out of range 0..{total_steps - 1}")
    done = list(alert.cm_steps_done or [])
    if step_index in done:
        return []
    done.append(step_index)
    alert.cm_steps_done = sorted(done)
    out = [Transition("COUNTERMEASURE_STEP_CONFIRMED", f"Step {step_index + 1}/{total_steps} confirmed", "CREW")]
    if len(alert.cm_steps_done) >= total_steps:
        alert.cm_status = CM_COMPLETED
        out.append(Transition("COUNTERMEASURE_COMPLETED", "All steps confirmed by crew; resolution still requires verified data", "CREW"))
    else:
        alert.cm_status = CM_IN_PROGRESS
    alert.updated_at = now
    return out


def clear(alert: AlertLike, now: datetime, actor: str = "CREW") -> list[Transition]:
    """CLEAR: only after verified resolution. Archives the alert, keeps history."""
    if alert.lifecycle == CLEARED:
        raise TransitionError("Alert is already cleared")
    if alert.lifecycle != RECOVERY or not alert.resolution_verified:
        raise TransitionError("Resolution not verified: condition must be nominal with fresh data for the recovery hold time")
    alert.lifecycle = CLEARED
    alert.cleared_at = now
    alert.cleared_by = actor
    alert.silenced = True
    alert.updated_at = now
    return [Transition("CLEARED", "Alert archived after verified resolution", actor)]


def display_states(alert: AlertLike) -> list[str]:
    states: list[str] = []
    if alert.lifecycle == CLEARED:
        return ["CLEARED"]
    if alert.kind == "SENSOR_FAULT":
        states.append("SENSOR_FAULT")
    elif alert.kind == "DATA_STALE":
        states.append("DATA_STALE")
    states.append(Severity(alert.severity).name)
    if alert.acknowledged:
        states.append("ACKNOWLEDGED")
    if alert.silenced:
        states.append("SILENCED")
    if alert.cm_status == CM_IN_PROGRESS:
        states.append("COUNTERMEASURE_IN_PROGRESS")
    if alert.cm_status == CM_COMPLETED:
        states.append("COUNTERMEASURE_COMPLETED")
    if alert.lifecycle == RECOVERY:
        states.append("RECOVERY")
        if alert.resolution_verified:
            states.append("RESOLUTION_VERIFIED")
    return states


def audio_required(alert: AlertLike) -> bool:
    return alert.lifecycle != CLEARED and not alert.silenced and alert.severity >= Severity.CAUTION
