import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.ai.incident_analyzer import IncidentAnalyzer
from backend.main import app
from backend.services import dispatch_service


client = TestClient(app)


def request(description):
    return client.post(
        "/incidents/analyze",
        json={"description": description, "location": {"lat": 28.61, "lng": 77.23, "name": "NH-44"}},
    )


@pytest.mark.parametrize(
    ("description", "services", "severity"),
    [
        ("Accident with one serious injury", {"POLICE", "AMBULANCE"}, "CRITICAL"),
        ("Vehicle breakdown on the highway", {"HIGHWAY_ASSISTANCE"}, "LOW"),
        ("Fire in a building", {"FIRE_RESCUE"}, "CRITICAL"),
        ("Accident with fire and injured people", {"POLICE", "AMBULANCE", "FIRE_RESCUE"}, "CRITICAL"),
    ],
)
def test_incident_analysis_selects_services(description, services, severity):
    result = request(description)
    assert result.status_code == 200
    body = result.json()
    assert body["analysis"]["severity"] == severity
    assert set(body["analysis"]["required_services"]) == services
    assert all(dispatch.get("unit_id") for dispatch in body["dispatches"] if dispatch["status"] == "DISPATCHED")


def test_llm_failure_uses_deterministic_fallback():
    class BrokenModel:
        async def ainvoke(self, _):
            raise RuntimeError("provider unavailable")

    analysis = asyncio.run(IncidentAnalyzer(model=BrokenModel()).analyze("Vehicle accident with injury", "NH-44"))
    assert analysis.severity == "CRITICAL"
    assert "POLICE" in analysis.required_services


def test_no_matching_unit_is_pending(monkeypatch):
    monkeypatch.setattr(dispatch_service, "_units", [])
    result = request("Vehicle breakdown on the highway")
    assert result.status_code == 200
    assert result.json()["status"] == "PENDING"
    assert result.json()["dispatches"][0]["status"] == "PENDING"


def test_missing_location_is_rejected():
    result = client.post("/incidents/analyze", json={"description": "Fire reported"})
    assert result.status_code == 422
