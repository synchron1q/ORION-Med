# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS tables. Created only when ORION_CFMS_ENABLED=true.

Source of truth:
  * the baseline Mission Plan lives ONLY in config/mission_plan.yaml and is never
    stored here;
  * RuntimeActivity holds unplanned activities added at runtime (crew entry,
    simulator, optional kRPC adapter). Ids start with RT- and cannot shadow or
    edit a baseline activity.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.models import UTCDateTime


class CfmsBase(DeclarativeBase):
    """Separate metadata: CFMS tables are never created while CFMS is disabled."""


class RuntimeActivity(CfmsBase):
    __tablename__ = "cfms_runtime_activities"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    activity_type: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    crew: Mapped[list] = mapped_column(JSON)
    start: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    end: Mapped[datetime] = mapped_column(UTCDateTime())
    device_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    source: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(12), default="ACTIVE")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    cancelled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class ExerciseSession(CfmsBase):
    """One program requirement (crew, exercise type, MET day, ordinal). The id is deterministic,
    so replanning can never create a duplicate session."""

    __tablename__ = "cfms_exercise_sessions"
    id: Mapped[str] = mapped_column(String(60), primary_key=True)
    crew_id: Mapped[str] = mapped_column(String(32), index=True)
    exercise_type: Mapped[str] = mapped_column(String(30))
    day_index: Mapped[int] = mapped_column(Integer, index=True)
    ordinal: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), index=True)
    device_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    planned_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    planned_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    conflict: Mapped[str | None] = mapped_column(String(40), nullable=True)
    plan_hash: Mapped[str] = mapped_column(String(16))
    notified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    actual_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    actual_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    gate_at_start: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    clearance_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    profile_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    pre_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_hr: Mapped[float | None] = mapped_column(Float, nullable=True)
    context: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    end_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ScheduleDecision(CfmsBase):
    """Full planner history: original window, conflict, reason, new window."""

    __tablename__ = "cfms_schedule_decisions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    session_id: Mapped[str] = mapped_column(String(60), index=True)
    crew_id: Mapped[str] = mapped_column(String(32))
    exercise_type: Mapped[str] = mapped_column(String(30))
    action: Mapped[str] = mapped_column(String(24))
    trigger: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(Text)
    conflict_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    conflict_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    from_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    from_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    from_device: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_start: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    to_end: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    to_device: Mapped[str | None] = mapped_column(String(20), nullable=True)
    plan_hash: Mapped[str] = mapped_column(String(16))


class MedicalClearance(CfmsBase):
    """Scoped to ONE crew member, ONE exercise type and a validity period. SIMULATED issuer."""

    __tablename__ = "cfms_medical_clearances"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    crew_id: Mapped[str] = mapped_column(String(32), index=True)
    exercise_type: Mapped[str] = mapped_column(String(30))
    valid_from: Mapped[datetime] = mapped_column(UTCDateTime())
    valid_until: Mapped[datetime] = mapped_column(UTCDateTime())
    issued_by: Mapped[str] = mapped_column(String(120))
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    revoked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EquipmentState(CfmsBase):
    """Runtime status of a SIMULATED device. The inventory itself lives in fitness.yaml."""

    __tablename__ = "cfms_equipment_state"
    device_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="MANUAL")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


