# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(settings, core):
    app = create_app(settings, core=core)
    with TestClient(app) as c:
        yield c


def test_health_and_docs(client):
    assert client.get("/api/v1/health").json()["status"] == "OK"
    assert client.get("/openapi.json").status_code == 200


def test_state_shape(client, core):
    core.simulator.enabled = True
    core.tick()
    j = client.get("/api/state").json()
    for key in ("mission", "parameters", "alerts", "master", "radiation", "sync", "timeline", "nasa_donki", "space_weather_simulation"):
        assert key in j
    assert j["nasa_donki"]["status"] in ("LIVE", "CACHED_OFFLINE", "OFFLINE_BASELINE")
    assert j["space_weather_simulation"] is None


def test_alert_actions_over_http(client, core, clock):
    r = client.post("/api/v1/telemetry", json={"parameter": "cabin_co2", "value": 7.5, "unit": "mmHg"})
    assert r.status_code == 200 and r.json()["accepted"] == 1
    alert = client.get("/api/v1/alerts").json()[0]
    assert alert["severity"] == "WARNING"
    assert client.post(f"/api/v1/alerts/{alert['id']}/ack").json()["lifecycle"] == "ACTIVE"
    assert client.post(f"/api/v1/alerts/{alert['id']}/silence").status_code == 200
    assert client.post(f"/api/v1/alerts/{alert['id']}/countermeasure", json={"step_index": 0}).json()["cm_status"] == "IN_PROGRESS"
    assert client.post(f"/api/v1/alerts/{alert['id']}/countermeasure", json={"step_index": 99}).status_code == 422
    assert client.post(f"/api/v1/alerts/{alert['id']}/resolve").status_code == 409
    assert client.get("/api/v1/alerts/nope").status_code == 404
    assert client.get(f"/api/v1/alerts/{alert['id']}").json()["history"][0]["event_type"] == "RAISED"


def test_telemetry_validation_http(client):
    assert client.post("/api/v1/telemetry", json={"parameter": "heart_rate", "value": 70, "unit": "Hz"}).status_code == 422
    assert client.post("/api/v1/telemetry", json={"parameter": "heart_rate", "value": 70, "quality": "MAYBE"}).status_code == 422
    r = client.post("/api/v1/telemetry", json={"records": [{"parameter": "heart_rate", "value": 70}, {"parameter": "bogus", "value": 1}]})
    assert r.json()["accepted"] == 1 and len(r.json()["rejected"]) == 1
    rows = client.get("/api/v1/telemetry", params={"parameter": "heart_rate"}).json()
    assert rows[0]["source"] == "SENSOR" and rows[0]["timestamp"].endswith("Z")


def test_simulator_endpoints(client, core):
    core.simulator.enabled = True
    assert client.post("/api/v1/simulator/HIGH_CO2").json()["scenario"] == "high_co2"
    assert client.post("/api/v1/simulator/meteor").status_code == 422
    assert client.post("/api/v1/simulator/link", json={"up": False}).json()["link_up"] is False
    assert client.get("/api/v1/mission/sync-status").json()["link_up"] is False
    client.post("/api/v1/simulator/solar_flare")
    assert client.get("/api/state").json()["space_weather_simulation"]["status"] == "SIMULATED"


def test_crew_endpoints(client):
    r = client.post("/api/v1/pvt/results", json={"reaction_times_ms": [280, 300], "misses": 0, "false_starts": 0, "duration_s": 10})
    assert r.status_code == 200 and r.json()["mean_rt_ms"] == 290
    assert len(client.get("/api/v1/pvt/history").json()["results"]) == 1
    assert client.post("/api/v1/psych/assessments", json={"mood": 3, "stress": 2, "fatigue": 3, "sleep_quality": 4}).json()["private"] is True
    assert client.post("/api/v1/psych/assessments", json={"mood": 9, "stress": 2, "fatigue": 3, "sleep_quality": 4}).status_code == 422


def test_reference_endpoints(client):
    assert len(client.get("/api/v1/protocols").json()) >= 8
    refs = client.get("/api/v1/references").json()
    assert {d["accession"] for d in refs["osdr_datasets"]} >= {"OSD-569", "OSD-360"}
    assert client.get("/api/v1/radiation").json()["budget_provenance"] == "DEMONSTRATION"
