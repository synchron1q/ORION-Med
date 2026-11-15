# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Configuration loader: parameter registry, protocols, zones, R.I.D.G.E. rules."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.engine.rules import Severity, ThresholdSet

CATEGORIES = {"physiological", "environmental", "radiation", "psychological"}
ZONES = ("head", "eyes", "cardiovascular", "respiratory", "musculoskeletal", "radiation")


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ParameterDef:
    id: str
    label: str
    short: str
    unit: str
    category: str
    zone: str
    valid_min: float
    valid_max: float
    thresholds: ThresholdSet
    stale_after_s: float
    stale_severity: Severity
    recovery_hold_s: float
    auto_clear: bool
    protocol: str | None
    sensor: str
    available: bool = True
    provenance: str = "DEMONSTRATION"

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "short": self.short,
            "unit": self.unit,
            "category": self.category,
            "zone": self.zone,
            "valid_range": [self.valid_min, self.valid_max],
            "thresholds": self.thresholds.as_dict(),
            "hysteresis": self.thresholds.hysteresis,
            "stale_after_s": self.stale_after_s,
            "recovery_hold_s": self.recovery_hold_s,
            "protocol": self.protocol,
            "sensor": self.sensor,
            "available": self.available,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class Protocol:
    id: str
    title: str
    description: str
    subsystem: str
    kit: str
    kit_contents: list[str]
    duration_min: float | None
    steps: list[str]
    resolution: str
    provenance: str

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "subsystem": self.subsystem,
            "kit": self.kit,
            "kit_contents": list(self.kit_contents),
            "duration_min": self.duration_min,
            "steps": list(self.steps),
            "resolution": self.resolution,
            "provenance": self.provenance,
        }


@dataclass
class Registry:
    parameters: dict[str, ParameterDef]
    protocols: dict[str, Protocol]
    zones: dict[str, dict[str, str]]
    ridge_rules: list[dict[str, Any]]
    mission: dict[str, Any]
    crew: list[dict[str, Any]]
    simulator: dict[str, Any]
    sync: dict[str, Any]
    space_weather: dict[str, Any]
    osdr: dict[str, Any]
    references: dict[str, Any]
    radiation: dict[str, Any] = field(default_factory=dict)

    def param(self, pid: str) -> ParameterDef:
        try:
            return self.parameters[pid]
        except KeyError as exc:
            raise ConfigError(f"Unknown parameter '{pid}'") from exc


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Missing configuration file: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration file must contain a mapping: {path}")
    return data


def load_registry(config_dir: Path) -> Registry:
    th = _read(config_dir / "demo_thresholds.yaml")
    cm = _read(config_dir / "countermeasures.yaml")
    md = _read(config_dir / "mission_defaults.yaml")
    refs = _read(config_dir / "references.yaml")

    defaults = th.get("defaults", {})
    protocols: dict[str, Protocol] = {}
    provenance = cm.get("provenance", "DEMONSTRATION PROCEDURE")
    for pid, p in (cm.get("protocols") or {}).items():
        steps = p.get("steps") or []
        if not steps:
            raise ConfigError(f"Protocol {pid} has no steps")
        protocols[pid] = Protocol(
            id=pid,
            title=p["title"],
            description=p["description"],
            subsystem=p["subsystem"],
            kit=p.get("kit", "NONE"),
            kit_contents=list(p.get("kit_contents") or []),
            duration_min=p.get("duration_min"),
            steps=[str(s) for s in steps],
            resolution=p.get("resolution", ""),
            provenance=provenance,
        )

    params: dict[str, ParameterDef] = {}
    for pid, p in (th.get("parameters") or {}).items():
        cat = p.get("category")
        if cat not in CATEGORIES:
            raise ConfigError(f"Parameter {pid}: invalid category {cat}")
        zone = p.get("zone")
        if zone not in ZONES:
            raise ConfigError(f"Parameter {pid}: invalid zone {zone}")
        lo, hi = p.get("valid_range", [None, None])
        protocol = p.get("protocol")
        if protocol and protocol not in protocols:
            raise ConfigError(f"Parameter {pid}: unknown protocol {protocol}")
        t = p.get("thresholds") or {}
        thresholds = ThresholdSet(
            advisory_high=t.get("advisory_high"),
            caution_high=t.get("caution_high"),
            warning_high=t.get("warning_high"),
            advisory_low=t.get("advisory_low"),
            caution_low=t.get("caution_low"),
            warning_low=t.get("warning_low"),
            hysteresis=float(p.get("hysteresis", defaults.get("hysteresis", 0))),
        )
        thresholds.validate(pid)
        params[pid] = ParameterDef(
            id=pid,
            label=p["label"],
            short=p.get("short", pid.upper()),
            unit=p["unit"],
            category=cat,
            zone=zone,
            valid_min=float(lo),
            valid_max=float(hi),
            thresholds=thresholds,
            stale_after_s=float(p.get("stale_after_s", defaults.get("stale_after_s", 8))),
            stale_severity=Severity[str(p.get("stale_severity", defaults.get("stale_severity", "CAUTION")))],
            recovery_hold_s=float(p.get("recovery_hold_s", defaults.get("recovery_hold_s", 5))),
            auto_clear=bool(p.get("auto_clear", defaults.get("auto_clear", False))),
            protocol=protocol,
            sensor=p.get("sensor", "UNSPECIFIED"),
            available=bool(p.get("available", True)),
        )

    for rule in th.get("ridge_rules") or []:
        for cond in (rule.get("conditions") or []) + (rule.get("any_of") or []):
            if "parameter" in cond and cond["parameter"] not in params:
                raise ConfigError(f"R.I.D.G.E. rule {rule.get('id')}: unknown parameter {cond['parameter']}")

    return Registry(
        parameters=params,
        protocols=protocols,
        zones=th.get("zones") or {},
        ridge_rules=th.get("ridge_rules") or [],
        mission=md.get("mission") or {},
        crew=md.get("crew") or [],
        simulator=md.get("simulator") or {},
        sync=md.get("sync") or {},
        space_weather=md.get("space_weather") or {},
        osdr=md.get("osdr") or {},
        references=refs,
        radiation=th.get("radiation") or {},
    )
