# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Runtime settings loaded from environment variables (see .env.example)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_VERSION = "1.0.7"


def _load_dotenv(path: Path) -> None:
    """Minimal .env reader (KEY=VALUE lines). Existing env vars win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    config_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "config")
    database_path: Path = field(default_factory=lambda: PROJECT_ROOT / "backend" / "data" / "orion_med.db")
    frontend_dist: Path = field(default_factory=lambda: PROJECT_ROOT / "frontend" / "dist")
    nasa_api_key: str = "DEMO_KEY"
    demo_mode: bool = True
    external_fetch_enabled: bool = True
    background_tasks: bool = True
    ground_sync_url: str = ""
    cfms_enabled: bool = False  # Crew Fitness Management System (ORION_CFMS_ENABLED)

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(PROJECT_ROOT / ".env")
        s = cls()
        if os.environ.get("ORION_CONFIG_DIR"):
            s.config_dir = Path(os.environ["ORION_CONFIG_DIR"])
        if os.environ.get("ORION_DB_PATH"):
            s.database_path = Path(os.environ["ORION_DB_PATH"])
        if os.environ.get("ORION_FRONTEND_DIST"):
            s.frontend_dist = Path(os.environ["ORION_FRONTEND_DIST"])
        s.nasa_api_key = os.environ.get("NASA_API_KEY", "").strip() or "DEMO_KEY"
        s.demo_mode = _bool("ORION_DEMO_MODE", True)
        s.external_fetch_enabled = _bool("ORION_EXTERNAL_FETCH", True)
        s.background_tasks = _bool("ORION_BACKGROUND_TASKS", True)
        s.ground_sync_url = os.environ.get("ORION_GROUND_SYNC_URL", "").strip()
        s.cfms_enabled = _bool("ORION_CFMS_ENABLED", False)
        return s
