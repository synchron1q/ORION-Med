# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
from app.engine.readiness import evaluate_eva_readiness, evaluate_triage_focus

from conftest import feed
from test_simulator import run, start


def ready(core, risk="NOMINAL"):
    state = core.dashboard()
    return core.readiness(state, {"space_weather_risk": risk, "is_placeholder": False})


def test_nominal_has_no_blockers_but_never_says_safe(core, clock):
    start(core, clock)
    r = ready(core)
    assert r["eva"]["status"] == "NO_BLOCKERS" and r["eva"]["gates_clear"] == 4
    assert "Decision support only" in r["eva"]["disclaimer"]
    assert r["triage"]["focus"] == "NOMINAL"


def test_missing_data_is_never_go(core, clock):
    start(core, clock)
    core.simulator.set_scenario("sensor_failure")
    run(core, clock, 3)
    r = ready(core)
    assert r["eva"]["status"] == "DATA_INCOMPLETE"
    cardio = next(g for g in r["eva"]["gates"] if g["id"] == "cardiorespiratory")
    assert cardio["status"] == "UNKNOWN" and any("not assumed normal" in x for x in cardio["reasons"])
    assert r["triage"]["focus"] == "INSTRUMENTATION" and r["triage"]["protocol_id"] == "CM-SENSOR-01"


def test_high_co2_focus_and_hold(core, clock):
    start(core, clock)
    core.simulator.set_scenario("high_co2")
    run(core, clock, 12)
    r = ready(core)
    assert r["eva"]["status"] == "HOLD_RECOMMENDED"
    assert r["triage"]["focus"] == "CABIN_CO2" and r["triage"]["kit"] == "KIT ECLSS-03"
    assert "not a diagnosis" in r["triage"]["disclaimer"]


def test_hypoxia_scenario(core, clock):
    start(core, clock)
    core.simulator.set_scenario("hypoxia")
    run(core, clock, 14)
    r = ready(core)
    alerts = {a["rule_id"]: a for a in core.list_alerts()}
    assert alerts["TH-spo2"]["severity"] == "WARNING" and "TH-cabin_o2" in alerts
    assert "RIDGE-SPO2-ATM" in alerts
    assert r["triage"]["focus"] == "OXYGENATION" and r["triage"]["kit"] == "KIT O2-A"
    assert any("cabin atmosphere" in c.lower() for c in r["triage"]["context"])


def test_space_weather_context_and_simulated_flare(core, clock):
    start(core, clock)
    assert ready(core, "CAUTION")["eva"]["status"] == "REVIEW"
    assert ready(core, "WARNING")["eva"]["status"] == "HOLD_RECOMMENDED"
    core.simulator.set_scenario("solar_flare")
    run(core, clock, 2)
    rad = next(g for g in ready(core)["eva"]["gates"] if g["id"] == "radiation")
    assert rad["status"] == "HOLD" and any("SIMULATED" in x for x in rad["reasons"])


def test_exercise_context_never_suppresses(core, clock):
    feed(core, clock, {"heart_rate": 125, "activity_level": 8})
    core.tick_monitor()
    t = ready(core)["triage"]
    assert t["focus"] == "HEART_RATE" and "physical activity" in t["rationale"]
    assert any(a["rule_id"] == "TH-heart_rate" for a in core.list_alerts())


def test_pure_functions_handle_empty_state():
    assert evaluate_eva_readiness({})["status"] == "DATA_INCOMPLETE"
    assert evaluate_triage_focus({}, {})["focus"] == "NOMINAL"


def test_readiness_endpoint(core):
    from fastapi.testclient import TestClient

    from app.main import create_app

    app = create_app(core.settings, core=core)
    with TestClient(app) as c:
        j = c.get("/api/v1/readiness").json()
        assert set(j) == {"eva", "triage"}
        assert "readiness" in c.get("/api/state").json()


def test_triage_prefers_active_over_recovering():
    state = {"alerts": [
        {"id": "o2", "rule_id": "TH-cabin_o2", "kind": "THRESHOLD", "severity": "CAUTION", "lifecycle": "RECOVERY", "message": "o2"},
        {"id": "rad", "rule_id": "TH-dose_rate", "kind": "THRESHOLD", "severity": "CAUTION", "lifecycle": "ACTIVE", "message": "rad"},
    ]}
    t = evaluate_triage_focus(state, {"CM-RAD-01": {"id": "CM-RAD-01", "kit": "KIT R-01"}})
    assert t["focus"] == "RADIATION" and t["kit"] == "KIT R-01"
