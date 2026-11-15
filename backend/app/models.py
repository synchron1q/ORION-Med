# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""SQLAlchemy ORM models for the local onboard database."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.database import Base


class UTCDateTime(TypeDecorator):
    """Stores naive UTC in SQLite and always returns timezone-aware UTC."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Naive datetimes are not allowed; use UTC-aware datetimes")
        return value.astimezone(timezone.utc).replace(tzinfo=None)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


class Mission(Base):
    __tablename__ = "missions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    environment: Mapped[str] = mapped_column(String(100))
    vehicle: Mapped[str] = mapped_column(String(200))
    met_start_utc: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())


class CrewMember(Base):
    __tablename__ = "crew_members"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"))
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(60))
    monitored: Mapped[bool] = mapped_column(Boolean, default=False)


class MissionConfiguration(Base):
    """Persisted runtime state (active scenario, comm link state, ...)."""

    __tablename__ = "mission_configuration"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"))
    value: Mapped[Any] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(40), default="RUNTIME")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())


class TelemetryRecord(Base):
    """Normalized telemetry: physiological, environmental, radiation and psychological."""

    __tablename__ = "telemetry_records"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    crew_id: Mapped[str | None] = mapped_column(ForeignKey("crew_members.id"), nullable=True)
    parameter: Mapped[str] = mapped_column(String(60))
    category: Mapped[str] = mapped_column(String(30))
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    unit: Mapped[str] = mapped_column(String(20))
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    source: Mapped[str] = mapped_column(String(30))
    quality: Mapped[str] = mapped_column(String(20))
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    __table_args__ = (Index("ix_telemetry_param_ts", "parameter", "timestamp"),)


class RadiationEvent(Base):
    __tablename__ = "radiation_events"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"))
    event_type: Mapped[str] = mapped_column(String(20))
    source: Mapped[str] = mapped_column(String(30))
    start_time: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    peak_time: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    class_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    meta: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class AlertEvent(Base):
    """One alert instance with its own lifecycle (see app.engine.alert_machine)."""

    __tablename__ = "alert_events"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    mission_id: Mapped[str] = mapped_column(ForeignKey("missions.id"), index=True)
    crew_id: Mapped[str | None] = mapped_column(ForeignKey("crew_members.id"), nullable=True)
    rule_id: Mapped[str] = mapped_column(String(80), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    parameter: Mapped[str | None] = mapped_column(String(60), nullable=True)
    zone: Mapped[str] = mapped_column(String(30))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    data_source: Mapped[str] = mapped_column(String(40))
    protocol_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    severity: Mapped[int] = mapped_column(Integer)
    peak_severity: Mapped[int] = mapped_column(Integer)
    lifecycle: Mapped[str] = mapped_column(String(20), index=True)
    acknowledged: Mapped[bool] = mapped_column(Boolean, default=False)
    silenced: Mapped[bool] = mapped_column(Boolean, default=False)
    cm_status: Mapped[str] = mapped_column(String(20))
    cm_steps_done: Mapped[list] = mapped_column(JSON, default=list)
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    trigger_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    recovery_since: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    resolution_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    factors: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime())
    cleared_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    cleared_by: Mapped[str | None] = mapped_column(String(20), nullable=True)


class AlertHistory(Base):
    __tablename__ = "alert_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alert_events.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    event_type: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")
    actor: Mapped[str] = mapped_column(String(20), default="SYSTEM")
    severity: Mapped[int] = mapped_column(Integer)
    lifecycle: Mapped[str] = mapped_column(String(20))


class CountermeasureExecution(Base):
    __tablename__ = "countermeasure_executions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("alert_events.id"), index=True)
    protocol_id: Mapped[str] = mapped_column(String(40))
    step_index: Mapped[int] = mapped_column(Integer)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    actor: Mapped[str] = mapped_column(String(20), default="CREW")


class PsychologicalAssessment(Base):
    __tablename__ = "psychological_assessments"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    crew_id: Mapped[str] = mapped_column(ForeignKey("crew_members.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime())
    mood: Mapped[int] = mapped_column(Integer)
    stress: Mapped[int] = mapped_column(Integer)
    fatigue: Mapped[int] = mapped_column(Integer)
    sleep_quality: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")
    private: Mapped[bool] = mapped_column(Boolean, default=True)


class PVTResult(Base):
    __tablename__ = "pvt_results"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    crew_id: Mapped[str] = mapped_column(ForeignKey("crew_members.id"), index=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    duration_s: Mapped[float] = mapped_column(Float)
    stimuli: Mapped[int] = mapped_column(Integer)
    responses: Mapped[int] = mapped_column(Integer)
    mean_rt_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    median_rt_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    lapses: Mapped[int] = mapped_column(Integer)
    misses: Mapped[int] = mapped_column(Integer)
    false_starts: Mapped[int] = mapped_column(Integer)
    reaction_times_ms: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(30))


class SyncQueueItem(Base):
    """Outbound (spacecraft -> ground) event queue. seq preserves ordering."""

    __tablename__ = "sync_queue"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(String(32), unique=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime())
    status: Mapped[str] = mapped_column(String(12), index=True, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class GroundReceipt(Base):
    """Receipts of the SIMULATED loopback ground station (duplicate detection)."""

    __tablename__ = "ground_receipts"
    item_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ExternalDataSnapshot(Base):
    __tablename__ = "external_data_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(30), index=True)
    feed: Mapped[str] = mapped_column(String(30), index=True)
    request_url: Mapped[str] = mapped_column(String(400))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    status: Mapped[str] = mapped_column(String(10))
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    payload: Mapped[Any] = mapped_column(JSON, nullable=True)


class MissionLogEntry(Base):
    """Non-alert mission events (scenario changes, comm link, space weather, crew input)."""

    __tablename__ = "mission_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    timestamp: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    category: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(30), default="SYSTEM")


class NasaWeatherCache(Base):
    """SQLite cache of NASA DONKI space-weather events (FLR, SEP). 15-minute TTL."""

    __tablename__ = "nasa_weather_cache"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    event_type: Mapped[str] = mapped_column(String(8))
    class_type: Mapped[str] = mapped_column(String(20))
    peak_time: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    active_region: Mapped[str | None] = mapped_column(String(20), nullable=True)
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
