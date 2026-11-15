# AI-assisted (Claude, Anthropic) under the ORION-MED team's specification - see AI_ATTRIBUTION.md
"""CFMS REST API and /api/state integration (enabled and disabled)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def off_client(settings, core):
    with TestClient(create_app(settings, core=core)) as c:
        yield c


@pytest.fixture
def client(settings, cfms_core):
    with TestClient(create_app(settings, core=cfms_core)) as c:
        yield c


def test_disabled_keeps_1_0_3_behaviour(off_client):
    assert off_client.get("/api/v1/fitness/status").status_code == 404
    assert "ORION_CFMS_ENABLED" in off_client.get("/api/v1/fitness/schedule").json()["detail"]
    assert off_client.get("/api/state").json()["fitness"] == {"enabled": False}
    assert off_client.get("/api/v1/health").json()["cfms_enabled"] is False


def test_state_block_and_reads(client):
    st = client.get("/api/state").json()["fitness"]
    assert st["enabled"] and len(st["next_by_crew"]) == 4
    assert st["plan"]["phase_now"]["type"] == "CRUISE"
    assert {e["id"] for e in st["equipment"]} == {"ERG-01", "TRD-01", "RES-01"}
    assert all("SIMULATED" in e["label"] for e in st["equipment"])
    cfg = client.get("/api/v1/fitness/config").json()
    assert "DEMONSTRATION" in cfg["provenance"] and cfg["profiles"]["EXP-AEROBIC-DEMO"]["provenance"] == "DEMONSTRATION"
    assert len(client.get("/api/v1/fitness/schedule", params={"crew_id": "CM-1"}).json()) == 6
    assert client.get("/api/v1/fitness/decisions").json()
    assert client.get("/api/v1/fitness/sessions/nope").status_code == 404


def test_plan_changes_over_http(client):
    r = client.post("/api/v1/fitness/plan/activities", json={"activity_type": "MANEUVER", "title": "Unplanned burn",
                                                              "start_in_min": 15, "duration_min": 20})
    assert r.status_code == 200 and r.json()["activity"]["origin"] == "RUNTIME"
    assert any(d["action"] == "MOVED" for d in r.json()["replan"]["decisions"])
    assert client.post("/api/v1/fitness/replan").json()["changes"] == 0
    assert client.delete("/api/v1/fitness/plan/activities/TCM-3").status_code == 409
    assert client.delete("/api/v1/fitness/plan/activities/RT-0001").status_code == 200
    bad = {"activity_type": "MANEUVER", "title": "x", "duration_min": 10, "start_in_min": 5, "start_met_h": 90}
    assert client.post("/api/v1/fitness/plan/activities", json=bad).status_code == 422
    assert client.post("/api/v1/fitness/plan/activities", json={**bad, "start_met_h": None, "activity_type": "PARTY"}).status_code == 422
    assert client.post("/api/v1/fitness/equipment/ERG-01", json={"status": "FAULT", "note": "test"}).json()["device"]["status"] == "FAULT"
    assert client.post("/api/v1/fitness/equipment/XYZ", json={"status": "FAULT"}).status_code == 404


def test_clearance_and_start_over_http(client, cfms_core, clock):
    from conftest import feed
    sid = "EX-D003-CM-2-AEROBIC-1"
    r = client.post(f"/api/v1/fitness/sessions/{sid}/start")
    assert r.status_code == 409 and r.json()["detail"]["gate"]["status"] == "BLOCKED"  # cabin not monitored yet
    feed(cfms_core, clock, {"cabin_co2": 2.0, "cabin_o2": 21.0, "cabin_pressure": 101.3})
    r = client.post(f"/api/v1/fitness/sessions/{sid}/start")
    assert r.status_code == 409 and r.json()["detail"]["gate"]["status"] == "CLEARANCE_REQUIRED"
    assert client.post("/api/v1/fitness/clearances", json={"crew_id": "CM-2", "issued_by": "X", "valid_hours": 2}).status_code == 422
    assert client.post("/api/v1/fitness/clearances", json={"crew_id": "CM-2", "exercise_type": "AEROBIC", "issued_by": "X",
                                                           "valid_hours": 30}).status_code == 422
    c = client.post("/api/v1/fitness/clearances", json={"crew_id": "CM-2", "exercise_type": "AEROBIC",
                                                        "issued_by": "Flight surgeon (SIMULATED)", "valid_hours": 2})
    assert c.status_code == 200 and c.json()["state"] == "ACTIVE"
    # CM-2 has no biosensor: the scoped clearance covers that, nothing else.
    r = client.post(f"/api/v1/fitness/sessions/{sid}/start")
    assert r.status_code == 200 and r.json()["clearance_id"] == c.json()["id"]
    assert client.post(f"/api/v1/fitness/sessions/{sid}/abort", json={"reason": ""}).status_code == 422
    assert client.post(f"/api/v1/fitness/sessions/{sid}/abort", json={"reason": "Crew call"}).json()["status"] == "ABORTED"
    assert client.post(f"/api/v1/fitness/clearances/{c.json()['id']}/revoke", json={"reason": "done"}).json()["state"] == "REVOKED"
