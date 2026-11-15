# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS request bodies."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Source = Literal["MANUAL", "SIMULATED", "KRPC"]


def _aware(v: datetime | None) -> datetime | None:
    if v is not None and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


class ActivityIn(BaseModel):
    """Unplanned runtime activity. Exactly one of start_met_h / start_utc / start_in_min."""

    activity_type: str
    title: str = Field(min_length=1, max_length=200)
    crew: list[str] = Field(default_factory=lambda: ["ALL"])
    start_met_h: float | None = None
    start_utc: datetime | None = None
    start_in_min: float | None = Field(default=None, ge=0, le=4320)
    duration_min: int = Field(ge=1, le=1440)
    device_id: str | None = None
    source: Source = "MANUAL"
    note: str = Field(default="", max_length=500)

    _tz = field_validator("start_utc")(lambda cls, v: _aware(v))

    @model_validator(mode="after")
    def one_start(self) -> "ActivityIn":
        given = [x is not None for x in (self.start_met_h, self.start_utc, self.start_in_min)]
        if sum(given) != 1:
            raise ValueError("Give exactly one of start_met_h, start_utc, start_in_min")
        return self


class EquipmentIn(BaseModel):
    status: Literal["OPERATIONAL", "DEGRADED", "FAULT", "MAINTENANCE"]
    note: str = Field(default="", max_length=300)
    source: Source = "MANUAL"


class ClearanceIn(BaseModel):
    """Scoped Medical Clearance: one crew member, one exercise type, limited validity."""

    crew_id: str = Field(min_length=1)
    exercise_type: str = Field(min_length=1)
    issued_by: str = Field(min_length=1, max_length=120)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    valid_hours: float | None = Field(default=None, gt=0, le=72)
    note: str = Field(default="", max_length=500)

    _tz = field_validator("valid_from", "valid_until")(lambda cls, v: _aware(v))

    @model_validator(mode="after")
    def one_end(self) -> "ClearanceIn":
        if (self.valid_until is None) == (self.valid_hours is None):
            raise ValueError("Give exactly one of valid_until or valid_hours")
        return self


class ReasonIn(BaseModel):
    reason: str = Field(default="", max_length=300)
