# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""Scenario tests: the simulator drives the normal ingest + rules pipeline."""
from conftest import alerts_by_rule


def run(core, clock, seconds):
    for _ in range(seconds):
        core.tick()
        clock.advance(1)


def start(core, clock, scenario="nominal"):
    core.simulator.enabled = True
    core.simulator.set_scenario(scenario)
    run(core, clock, 3)


def test_nominal_has_no_alerts(core, clock):
    start(core, clock)
    run(core, clock, 20)
    assert core.list_alerts() == []
    assert all(p["status"] in ("OK", "NOT_INSTRUMENTED") for p in core.parameter_states())
    assert all(p["source"] in (None, "SIMULATED") for p in core.parameter_states())


def test_high_co2_demo_script(core, clock):
    """Mirrors the 30-second demonstration script."""
    start(core, clock)
    core.simulator.set_scenario("high_co2")
    run(core, clock, 9)
    a = alerts_by_rule(core)["TH-cabin_co2"]
    assert a["severity"] == "WARNING" and a["zone"] == "respiratory" and a["simulated"]
    proto = core.reg.protocols[a["protocol_id"]]
    assert proto.kit == "KIT ECLSS-03"
    acked = core.acknowledge(a["id"])
    assert acked["lifecycle"] == "ACTIVE" and acked["silenced"]
    core.confirm_step(a["id"], 0)
    core.confirm_step(a["id"], 1)
    run(core, clock, 6)
    assert "RIDGE-CO2-COG" in alerts_by_rule(core)
    core.simulator.set_scenario("nominal")
    run(core, clock, 9)
    a = alerts_by_rule(core)["TH-cabin_co2"]
    assert a["lifecycle"] == "RECOVERY"
    run(core, clock, 6)
    a = alerts_by_rule(core)["TH-cabin_co2"]
    assert a["can_clear"]
    core.resolve(a["id"])
    log = core.timeline(200)
    assert any("CLEARED" in e["message"] and e["category"] == "ALERT" for e in log)
    assert any("HIGH CO2" in e["message"] for e in log)


def test_tachycardia(core, clock):
    start(core, clock)
    core.simulator.set_scenario("tachycardia")
    run(core, clock, 14)
    a = alerts_by_rule(core)
    assert a["TH-heart_rate"]["severity"] == "WARNING" and a["TH-heart_rate"]["zone"] == "cardiovascular"
    assert "RIDGE-HR-ACT" not in a, "no exercise context at rest"


def test_solar_flare(core, clock):
    start(core, clock)
    core.simulator.set_scenario("solar_flare")
    run(core, clock, 12)
    a = alerts_by_rule(core)
    assert a["TH-dose_rate"]["severity"] == "WARNING" and a["TH-dose_rate"]["zone"] == "radiation"
    assert "RIDGE-RAD-SWX" in a
    assert core.simulator.simulated_space_weather()["status"] == "SIMULATED"
    assert any(e["source"] == "SIMULATED" for e in core.radiation_summary()["events"])


def test_sensor_failure(core, clock):
    start(core, clock)
    core.simulator.set_scenario("sensor_failure")
    run(core, clock, 2)
    a = alerts_by_rule(core)
    assert "FAULT-heart_rate" in a and "FAULT-hrv" in a
    run(core, clock, 9)
    a = alerts_by_rule(core)
    assert "STALE-heart_rate" in a
    hr = next(p for p in core.parameter_states() if p["id"] == "heart_rate")
    assert hr["status"] == "SENSOR_FAULT" and hr["band"] is None
    core.simulator.set_scenario("nominal")
    run(core, clock, 10)
    assert not any(k.startswith(("FAULT-heart", "STALE-heart")) for k in alerts_by_rule(core))


def test_unknown_scenario(core):
    import pytest

    with pytest.raises(ValueError):
        core.simulator.set_scenario("meteor")
