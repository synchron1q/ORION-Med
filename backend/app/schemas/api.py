# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Pydantic request/response schemas for the REST API."""
from __future__ import annotations

import math
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Source = Literal["SENSOR", "SIMULATED", "CREW_INPUT", "IMPORTED"]
Quality = Literal["GOOD", "SUSPECT", "FAULT"]


class TelemetryIn(BaseModel):
    parameter: str = Field(min_length=1, max_length=60, examples=["heart_rate"])
    value: float | None = Field(default=None, examples=[78])
    unit: str | None = Field(default=None, examples=["bpm"])
    timestamp: datetime | None = Field(default=None, description="UTC ISO-8601 with timezone. Defaults to server time.")
    source: Source = "SENSOR"
    quality: Quality = "GOOD"
    crew_id: str | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("value")
    @classmethod
    def finite(cls, v: float | None) -> float | None:
        if v is not None and not math.isfinite(v):
            raise ValueError("value must be finite")
        return v


class TelemetryBatchIn(BaseModel):
    records: list[TelemetryIn] = Field(min_length=1, max_length=500)


class IngestResult(BaseModel):
    accepted: int
    rejected: list[dict[str, Any]]


class TelemetryRecordOut(BaseModel):
    id: str
    parameter: str
    category: str
    value: float | None
    unit: str
    timestamp: str
    source: str
    quality: str
    mission_id: str
    crew_id: str | None
    metadata: dict[str, Any] | None


class AlertOut(BaseModel):
    id: str
    rule_id: str
    kind: str
    parameter: str | None
    zone: str
    title: str
    message: str
    data_source: str
    simulated: bool
    protocol_id: str | None
    severity: str
    peak_severity: str
    lifecycle: str
    acknowledged: bool
    silenced: bool
    cm_status: str
    cm_steps_done: list[int]
    unit: str | None
    trigger_value: float | None
    last_value: float | None
    occurrence_count: int
    recovery_since: str | None
    resolution_verified: bool
    recovery_hold_s: float
    factors: list[dict[str, Any]] | None
    created_at: str
    updated_at: str
    cleared_at: str | None
    cleared_by: str | None
    states: list[str]
    audio_required: bool
    can_clear: bool
    history: list[dict[str, Any]] | None = None


class CountermeasureIn(BaseModel):
    step_index: int = Field(ge=0, le=50)


class PVTIn(BaseModel):
    reaction_times_ms: list[float] = Field(max_length=50)
    misses: int = Field(ge=0, le=50)
    false_starts: int = Field(ge=0, le=50)
    duration_s: float = Field(gt=0, le=600)


class PsychIn(BaseModel):
    mood: int = Field(ge=1, le=5)
    stress: int = Field(ge=1, le=5)
    fatigue: int = Field(ge=1, le=5)
    sleep_quality: int = Field(ge=1, le=5)
    notes: str = Field(default="", max_length=1000)
    private: bool = True


class LinkIn(BaseModel):
    up: bool


class SimulatorControlIn(BaseModel):
    enabled: bool
