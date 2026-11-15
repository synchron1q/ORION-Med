# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Typed shape of GET /api/state (HevSystemState)."""
from __future__ import annotations

from typing import Any, TypedDict

from app.integrations.nasa_donki import NasaDonkiContext


class HevSystemState(TypedDict, total=False):
    server_time: str
    version: str
    mission: dict[str, Any]
    mode: dict[str, Any]
    medical_status: str
    system_health: dict[str, Any]
    master: dict[str, Any]
    zones: dict[str, dict[str, str]]
    parameters: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    recent_cleared: list[dict[str, Any]]
    events: list[dict[str, Any]]
    latest_event_seq: int
    radiation: dict[str, Any]
    sync: dict[str, Any]
    timeline: list[dict[str, Any]]
    nasa_donki: NasaDonkiContext
    space_weather_simulation: dict[str, Any] | None
    readiness: dict[str, Any]
    fitness: dict[str, Any]
    ksp: dict[str, Any]
