# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.settings import Settings  # noqa: E402
from app.services.core import HevCore, TelemetryInput  # noqa: E402


class Clock:
    def __init__(self, start: datetime | None = None):
        self.t = start or datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.t

    def advance(self, seconds: float) -> datetime:
        self.t += timedelta(seconds=seconds)
        return self.t


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings.from_env()
    s.database_path = tmp_path / "test.db"
    s.background_tasks = False
    s.external_fetch_enabled = False
    s.demo_mode = True
    s.ground_sync_url = ""
    s.cfms_enabled = False  # CFMS tests use the cfms_core fixture
    return s


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def core(settings: Settings, clock: Clock) -> HevCore:
    c = HevCore(settings, now_fn=clock)
    c.simulator.enabled = False  # tests drive telemetry explicitly unless they enable it
    yield c
    c.engine.dispose()


@pytest.fixture
def cfms_core(settings: Settings, clock: Clock) -> HevCore:
    settings.cfms_enabled = True
    c = HevCore(settings, now_fn=clock)
    c.simulator.enabled = False
    yield c
    c.engine.dispose()


def feed(core: HevCore, clock: Clock, values: dict[str, float], source: str = "SENSOR", quality: str = "GOOD") -> dict:
    items = [TelemetryInput(k, v, core.reg.parameters[k].unit, clock(), source, quality) for k, v in values.items()]
    return core.ingest(items)


def alerts_by_rule(core: HevCore, include_cleared: bool = False) -> dict[str, dict]:
    return {a["rule_id"]: a for a in core.list_alerts(include_cleared=include_cleared)}
