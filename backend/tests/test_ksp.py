"""Tests for the KSP 1 OrionMedKSP VesselModule telemetry bridge (/api/v1/ksp/* and /api/state.ksp)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(settings, core):
    app = create_app(settings, core=core)
    with TestClient(app) as c:
        yield c


def test_ksp_bridge_sync_and_flight_hazard_alerts(client):
    r0 = client.get("/api/v1/ksp/status")
    assert r0.status_code == 200
    assert r0.json()["connected"] is False

    # 1. Выход в открытый космос (OPEN_SPACE: высота > 70 км на Кербине / орбита)
    open_space_payload = {
        "vessel_name": "ORION MPCV-1",
        "situation": "ORBITING",
        "body": "Kerbin",
        "altitude_m": 85000.0,
        "g_force": 0.0,
        "mach": 0.0,
        "met_s": 420.0,
        "eva_active": False,
        "emotion": "Neutral",
        "consciousness": "Alert",
        "primary_cause": "Orbiting",
        "critical_timer_s": 0.0,
        "lethal_limit_s": 30.0,
        "ingest_biometrics": True,
        "crew": [
            {
                "name": "Jebediah Kerman",
                "trait": "Pilot",
                "type": "Crew",
                "inactive": False,
                "state_label": "IN_COMMAND",
            }
        ],
    }

    r1 = client.post("/api/v1/ksp/sync", json=open_space_payload)
    assert r1.status_code == 200
    data1 = r1.json()
    assert data1["connected"] is True
    assert data1["hazard_phase"] == "OPEN_SPACE"

    st1 = client.get("/api/state").json()
    assert st1["medical_status"] == "WARNING"
    rule_ids_1 = {a["rule_id"] for a in st1["alerts"]}
    assert "TH-cabin_co2" in rule_ids_1 or "TH-dose_rate" in rule_ids_1

    # 2. Выход кербала за борт в открытый космос (EVA_OPEN_SPACE)
    eva_payload = {**open_space_payload, "eva_active": True, "vessel_name": "Jebediah Kerman (EVA)"}
    r2 = client.post("/api/v1/ksp/sync", json=eva_payload)
    assert r2.status_code == 200
    assert r2.json()["hazard_phase"] == "EVA_OPEN_SPACE"

    st2 = client.get("/api/state").json()
    assert st2["medical_status"] == "WARNING"
    rule_ids_2 = {a["rule_id"] for a in st2["alerts"]}
    assert "TH-spo2" in rule_ids_2

    # 3. Вход в атмосферу (ATMOS_ENTRY: снижение < 70 км с перегрузкой и числом Маха)
    reentry_payload = {
        **open_space_payload,
        "eva_active": False,
        "situation": "FLYING",
        "altitude_m": 42000.0,
        "g_force": 4.2,
        "mach": 5.8,
    }
    r3 = client.post("/api/v1/ksp/sync", json=reentry_payload)
    assert r3.status_code == 200
    assert r3.json()["hazard_phase"] == "ATMOS_ENTRY"

    st3 = client.get("/api/state").json()
    assert st3["medical_status"] == "WARNING"
    rule_ids_3 = {a["rule_id"] for a in st3["alerts"]}
    assert "TH-bp_systolic" in rule_ids_3 or "TH-heart_rate" in rule_ids_3
