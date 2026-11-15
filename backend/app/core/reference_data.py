# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""NASA reference values (config/nasa_reference_dataset.yaml): context only, never an alarm limit."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.core.registry import ConfigError

VALUE_TYPES = ("STANDARD_REQUIREMENT", "OBSERVED_STATISTIC", "PROGRAM_TARGET")
REQUIRED = ("id", "group", "label", "value", "unit", "value_type", "source")


def load_reference_data(config_dir: Path) -> dict[str, Any]:
    path = config_dir / "nasa_reference_dataset.yaml"
    if not path.is_file():
        return {"provenance": "not configured", "verified_on": None, "sources": {}, "values": []}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    sources = data.get("sources") or {}
    for sid, src in sources.items():
        if not str(src.get("url", "")).startswith("https://"):
            raise ConfigError(f"nasa_reference_dataset.yaml: source {sid} needs an https URL")
    seen: set[str] = set()
    values = []
    for v in data.get("values") or []:
        missing = [k for k in REQUIRED if k not in v]
        if missing:
            raise ConfigError(f"nasa_reference_dataset.yaml: {v.get('id')} misses {', '.join(missing)}")
        if v["value_type"] not in VALUE_TYPES:
            raise ConfigError(f"nasa_reference_dataset.yaml: {v['id']}: invalid value_type {v['value_type']}")
        if v["source"] not in sources:
            raise ConfigError(f"nasa_reference_dataset.yaml: {v['id']}: unknown source {v['source']}")
        if v["id"] in seen:
            raise ConfigError(f"nasa_reference_dataset.yaml: duplicate id {v['id']}")
        seen.add(v["id"])
        values.append({**v, "source_title": sources[v["source"]]["title"], "source_url": sources[v["source"]]["url"]})
    return {"provenance": data.get("provenance", ""), "verified_on": str(data.get("verified_on") or ""),
            "sources": sources, "values": values}
