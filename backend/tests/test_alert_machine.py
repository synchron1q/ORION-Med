# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
from datetime import datetime, timedelta, timezone

import pytest

from app.engine import alert_machine as am
from app.engine.rules import Severity

T0 = datetime(2026, 11, 14, tzinfo=timezone.utc)


def new(sev=Severity.CAUTION, protocol=True):
    a = am.AlertState()
    am.init_alert(a, sev, T0, has_protocol=protocol)
    return a


def types(trs):
    return [t.event_type for t in trs]


def test_init_requires_non_nominal():
    with pytest.raises(am.TransitionError):
        am.init_alert(am.AlertState(), Severity.NOMINAL, T0, True)


def test_ack_silences_but_never_clears():
    a = new(Severity.WARNING)
    assert types(am.acknowledge(a, T0)) == ["ACKNOWLEDGED"]
    assert a.acknowledged and a.silenced
    assert a.lifecycle == am.ACTIVE and a.severity == Severity.WARNING
    assert "WARNING" in am.display_states(a) and "ACKNOWLEDGED" in am.display_states(a)
    assert am.acknowledge(a, T0) == []  # idempotent


def test_silence_keeps_visual_alert():
    a = new()
    am.silence(a, T0)
    assert a.silenced and not a.acknowledged and a.lifecycle == am.ACTIVE
    assert not am.audio_required(a)


def test_escalation_resets_ack_and_deescalation_keeps_it():
    a = new(Severity.CAUTION)
    am.acknowledge(a, T0)
    assert types(am.on_condition(a, Severity.WARNING, T0, 5, False)) == ["ESCALATED"]
    assert not a.acknowledged and not a.silenced and a.peak_severity == Severity.WARNING
    am.acknowledge(a, T0)
    assert types(am.on_condition(a, Severity.CAUTION, T0, 5, False)) == ["DEESCALATED"]
    assert a.acknowledged and a.peak_severity == Severity.WARNING


def test_recovery_requires_hold_then_manual_clear():
    a = new(Severity.WARNING)
    assert types(am.on_condition(a, Severity.NOMINAL, T0, 5, False)) == ["RECOVERY_STARTED"]
    with pytest.raises(am.TransitionError):
        am.clear(a, T0)
    assert am.on_condition(a, Severity.NOMINAL, T0 + timedelta(seconds=4), 5, False) == []
    assert types(am.on_condition(a, Severity.NOMINAL, T0 + timedelta(seconds=5), 5, False)) == ["RESOLUTION_VERIFIED"]
    assert a.lifecycle == am.RECOVERY and "RESOLUTION_VERIFIED" in am.display_states(a)
    assert types(am.clear(a, T0 + timedelta(seconds=6))) == ["CLEARED"]
    assert am.display_states(a) == ["CLEARED"]


def test_auto_clear_when_configured():
    a = new(Severity.ADVISORY)
    am.on_condition(a, Severity.NOMINAL, T0, 5, True)
    assert types(am.on_condition(a, Severity.NOMINAL, T0 + timedelta(seconds=5), 5, True)) == ["RESOLUTION_VERIFIED", "CLEARED"]
    assert a.cleared_by == "SYSTEM"


def test_relapse_during_recovery():
    a = new(Severity.CAUTION)
    am.acknowledge(a, T0)
    am.on_condition(a, Severity.NOMINAL, T0, 5, False)
    assert types(am.on_condition(a, Severity.CAUTION, T0 + timedelta(seconds=2), 5, False)) == ["RECURRED"]
    assert a.lifecycle == am.ACTIVE and a.occurrence_count == 2 and not a.acknowledged


def test_hysteresis_band_restarts_recovery_and_revokes_verification():
    a = new()
    am.on_condition(a, Severity.NOMINAL, T0, 5, False)
    am.on_condition(a, Severity.NOMINAL, T0 + timedelta(seconds=6), 5, False)
    assert a.resolution_verified
    assert types(am.on_hysteresis_band(a, T0 + timedelta(seconds=7))) == ["RESOLUTION_REVOKED"]
    assert not a.resolution_verified and a.recovery_since == T0 + timedelta(seconds=7)


def test_countermeasure_progress_does_not_resolve():
    a = new(Severity.WARNING)
    assert types(am.confirm_step(a, 0, 3, T0)) == ["COUNTERMEASURE_STEP_CONFIRMED"]
    assert a.cm_status == am.CM_IN_PROGRESS and "COUNTERMEASURE_IN_PROGRESS" in am.display_states(a)
    assert am.confirm_step(a, 0, 3, T0) == []
    am.confirm_step(a, 1, 3, T0)
    assert types(am.confirm_step(a, 2, 3, T0)) == ["COUNTERMEASURE_STEP_CONFIRMED", "COUNTERMEASURE_COMPLETED"]
    assert a.cm_status == am.CM_COMPLETED and a.lifecycle == am.ACTIVE and a.severity == Severity.WARNING
    with pytest.raises(am.TransitionError):
        am.confirm_step(a, 7, 3, T0)


def test_no_protocol_no_countermeasure():
    a = new(protocol=False)
    with pytest.raises(am.TransitionError):
        am.confirm_step(a, 0, 3, T0)


def test_cleared_alert_rejects_actions():
    a = new(Severity.ADVISORY)
    am.on_condition(a, Severity.NOMINAL, T0, 0, True)
    assert a.lifecycle == am.CLEARED
    for fn in (lambda: am.acknowledge(a, T0), lambda: am.silence(a, T0), lambda: am.clear(a, T0),
               lambda: am.on_condition(a, Severity.WARNING, T0, 5, False)):
        with pytest.raises(am.TransitionError):
            fn()


def test_kind_states():
    a = new()
    a.kind = "SENSOR_FAULT"
    assert am.display_states(a)[0] == "SENSOR_FAULT"
    a.kind = "DATA_STALE"
    assert am.display_states(a)[0] == "DATA_STALE"
