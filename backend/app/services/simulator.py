# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Mission simulator. Produces SIMULATED telemetry through the normal ingest path.

There is no separate alert mechanism: every scenario only changes the
simulated sensor values; the rules engine reacts exactly as it would to
real sensors. All generated records carry source=SIMULATED.
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from app.models import RadiationEvent

if TYPE_CHECKING:
    from app.services.core import HevCore

SCENARIOS: dict[str, dict[str, str]] = {
    "nominal": {"label": "NOMINAL", "description": "All simulated parameters return to configured demonstration ranges."},
    "high_co2": {"label": "HIGH CO2", "description": "Cabin CO2 rises above the configured warning limit; breathing, heart rate and PVT reaction time drift."},
    "solar_flare": {"label": "SOLAR FLARE", "description": "Simulated X-class flare with solar particle onset; dosimeter dose rate rises above the warning limit."},
    "tachycardia": {"label": "TACHYCARDIA", "description": "Heart rate rises above the configured warning limit at rest (no exercise)."},
    "hypoxia": {"label": "HYPOXIA", "description": "SpO2 falls below 85 % (configured warning limit 90 %) while cabin O2 concentration and pressure decrease."},
    "hemorrhage": {"label": "HEMORRHAGE", "description": "Simulated blood loss: systolic blood pressure falls below the configured warning limit while heart rate rises above 130 bpm at rest."},
    "sensor_failure": {"label": "SENSOR FAILURE", "description": "Chest biosensor reports a fault, then stops transmitting (HR, HRV)."},
}

BASE: dict[str, float] = {
    "heart_rate": 72.0, "hrv": 55.0, "spo2": 98.0, "body_temp": 36.8, "resp_rate": 14.0,
    "activity_level": 1.4, "bp_systolic": 118.0, "cabin_co2": 2.0, "cabin_pressure": 101.3, "cabin_o2": 21.0,
    "cabin_temp": 22.0, "humidity": 45.0, "dose_rate": 18.0,
}
OVERRIDES: dict[str, dict[str, float]] = {
    "hemorrhage": {"bp_systolic": 76.0, "heart_rate": 136.0, "resp_rate": 23.0},
    "high_co2": {"cabin_co2": 8.2, "heart_rate": 92.0, "resp_rate": 19.0},
    "solar_flare": {"dose_rate": 900.0},
    "tachycardia": {"heart_rate": 146.0, "hrv": 16.0, "resp_rate": 20.0},
    "hypoxia": {"spo2": 84.0, "resp_rate": 23.0, "heart_rate": 98.0, "cabin_o2": 18.6, "cabin_pressure": 97.5},
}
FAILED_SENSORS: dict[str, tuple[str, ...]] = {"sensor_failure": ("heart_rate", "hrv")}
# Maximum change per second (how fast the simulated value follows its target).
RATE: dict[str, float] = {
    "heart_rate": 7.0, "hrv": 4.0, "bp_systolic": 4.0, "spo2": 1.5, "body_temp": 0.05, "resp_rate": 1.0, "activity_level": 1.0,
    "cabin_co2": 0.85, "cabin_pressure": 0.5, "cabin_o2": 0.2, "cabin_temp": 0.2, "humidity": 1.0, "dose_rate": 160.0,
}
NOISE: dict[str, float] = {
    "heart_rate": 0.8, "hrv": 1.2, "bp_systolic": 1.0, "spo2": 0.15, "body_temp": 0.02, "resp_rate": 0.3, "activity_level": 0.05,
    "cabin_co2": 0.04, "cabin_pressure": 0.04, "cabin_o2": 0.03, "cabin_temp": 0.04, "humidity": 0.3, "dose_rate": 1.2,
}
PVT_TARGET = {"nominal": 265.0, "high_co2": 440.0}
PVT_INTERVAL_S = 15
SLEEP_INTERVAL_S = 30
SIMULATED_SLEEP_H = 7.2
INITIAL_DOSE_MGY = 1.6


class Simulator:
    def __init__(self, core: "HevCore"):
        self.core = core
        cfg = core.reg.simulator
        self.rng = random.Random(int(cfg.get("seed", 2026)))
        self.enabled = bool(core.settings.demo_mode and core.get_runtime("simulator.enabled", cfg.get("enabled_by_default", True)))
        scenario = core.get_runtime("simulator.scenario", cfg.get("default_scenario", "nominal"))
        self.scenario = scenario if scenario in SCENARIOS else "nominal"
        self.values = {pid: (core.state[pid].last_valid_value if core.state[pid].last_valid_value is not None else v) for pid, v in BASE.items()}
        acc = core.state["accumulated_dose"].last_valid_value
        self.accumulated = acc if acc is not None else INITIAL_DOSE_MGY
        self.last_tick: datetime | None = None
        self.last_pvt: datetime | None = None
        self.last_sleep: datetime | None = None
        self.fault_sent: set[str] = set()
        self.scenario_started = core.now()

    # ---------------------------------------------------------------- control
    def scenario_list(self) -> list[dict[str, Any]]:
        return [{"id": k, **v, "active": k == self.scenario} for k, v in SCENARIOS.items()]

    def set_scenario(self, scenario: str) -> dict[str, Any]:
        if scenario not in SCENARIOS:
            raise ValueError(f"Unknown scenario '{scenario}'. Valid: {', '.join(SCENARIOS)}")
        core = self.core
        with core.lock, core.Session() as s:
            self.scenario = scenario
            self.scenario_started = core.now()
            self.fault_sent.clear()
            core.set_runtime("simulator.scenario", scenario, s)
            core.log("SIMULATOR", f"Scenario {SCENARIOS[scenario]['label']} activated (simulated data)", "SIMULATOR", s)
            if scenario == "solar_flare":
                now = core.now()
                stamp = now.strftime("%Y%m%dT%H%M%S")
                s.add(RadiationEvent(id=f"SIM-FLR-{stamp}", mission_id=core.mission_id, event_type="FLR", source="SIMULATED",
                                     start_time=now, peak_time=now + timedelta(seconds=30), class_type="X1.0",
                                     description="Simulated X-class solar flare (demonstration scenario)"))
                s.add(RadiationEvent(id=f"SIM-SEP-{stamp}", mission_id=core.mission_id, event_type="SEP", source="SIMULATED",
                                     start_time=now + timedelta(seconds=5), class_type="SEP_EVENT",
                                     description="Simulated solar energetic particle onset (demonstration scenario)"))
            s.commit()
        return self.status()

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        if enabled and not self.core.settings.demo_mode:
            raise ValueError("The simulator is only available in demonstration mode (ORION_DEMO_MODE=true)")
        self.enabled = enabled
        self.core.set_runtime("simulator.enabled", enabled)
        self.core.log("SIMULATOR", "Simulator " + ("started" if enabled else "stopped"), "SIMULATOR")
        self.last_tick = None
        return self.status()

    def status(self) -> dict[str, Any]:
        return {"enabled": self.enabled, "scenario": self.scenario, "scenarios": self.scenario_list(),
                "scenario_started": self.scenario_started.isoformat(), "demo_mode": self.core.settings.demo_mode}

    def simulated_space_weather(self) -> dict[str, Any] | None:
        """Shown only while the SOLAR_FLARE scenario is explicitly active."""
        if not (self.enabled and self.scenario == "solar_flare"):
            return None
        return {
            "status": "SIMULATED",
            "latest_event": "Solar Flare X1.0 + SEP onset (SIMULATED demonstration scenario)",
            "space_weather_risk": "WARNING",
            "eva_advisory": "EVA HOLD RECOMMENDED",
            "radiation_context": "Simulated solar particle event. The onboard dosimeter values in this scenario are simulated as well.",
            "started_at": self.scenario_started.isoformat(),
            "source": "HEV-1 MISSION SIMULATOR",
        }

    # ------------------------------------------------------------------ tick
    def tick(self) -> None:
        from app.services.core import TelemetryInput

        core = self.core
        now = core.now()
        dt = 1.0 if self.last_tick is None else max(0.0, min(5.0, (now - self.last_tick).total_seconds()))
        self.last_tick = now
        targets = dict(BASE)
        fitness = getattr(core, "fitness", None)
        if fitness is not None:  # SIMULATED exercise load (CFMS); a scenario takes precedence
            targets.update({k: v for k, v in fitness.simulated_load_targets().items() if k in BASE})
        targets.update(OVERRIDES.get(self.scenario, {}))
        failed = FAILED_SENSORS.get(self.scenario, ())
        records: list[TelemetryInput] = []
        for pid, target in targets.items():
            pdef = core.reg.parameters[pid]
            current = self.values[pid]
            step = RATE[pid] * dt
            current += max(-step, min(step, target - current))
            self.values[pid] = current
            if pid in failed:
                if pid not in self.fault_sent:
                    self.fault_sent.add(pid)
                    records.append(TelemetryInput(pid, None, pdef.unit, now, "SIMULATED", "FAULT",
                                                  metadata={"reason": "loss of skin contact reported (SIMULATED)"}))
                continue  # failed sensor stops transmitting
            value = current + self.rng.gauss(0.0, NOISE[pid])
            value = round(max(pdef.valid_min, min(pdef.valid_max, value)), 2)
            records.append(TelemetryInput(pid, value, pdef.unit, now, "SIMULATED", "GOOD"))

        self.accumulated += self.values["dose_rate"] * dt / 3_600_000.0  # uGy/h * s -> mGy
        records.append(TelemetryInput("accumulated_dose", round(self.accumulated, 5), "mGy", now, "SIMULATED", "GOOD"))

        if self.last_sleep is None or (now - self.last_sleep).total_seconds() >= SLEEP_INTERVAL_S:
            self.last_sleep = now
            records.append(TelemetryInput("sleep_hours", SIMULATED_SLEEP_H, "h", now, "SIMULATED", "GOOD"))
        if self.last_pvt is None or (now - self.last_pvt).total_seconds() >= PVT_INTERVAL_S:
            self.last_pvt = now
            target = PVT_TARGET.get(self.scenario, PVT_TARGET["nominal"])
            records.append(TelemetryInput("pvt_mean_rt", round(target + self.rng.gauss(0, 10), 1), "ms", now, "SIMULATED", "GOOD",
                                          metadata={"note": "Simulated PVT summary"}))
        core.ingest(records)
