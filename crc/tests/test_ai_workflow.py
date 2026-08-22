import asyncio

import pytest
from fastapi.testclient import TestClient

from backend.ai.incident_analyzer import IncidentAnalyzer
from backend.agents.replanning_agent import ReplanningAgent
from backend.main import app
from backend.models.incident import Incident
from backend.models.unit import Unit
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


def make_incident():
    return Incident(type="medical", severity="high", lat=28.61, lng=77.23, location_name="Test location")


@pytest.mark.parametrize(("failed_type", "replacement_id"), [("ambulance", "AMB-02"), ("police", "POL-02")])
def test_breakdown_selects_nearest_same_type_unit(failed_type, replacement_id):
    failed = Unit(id=f"{failed_type}-failed", type=failed_type, name="Failed", lat=28.61, lng=77.23, status="dispatched")
    replacement = Unit(id=replacement_id, type=failed_type, name="Replacement", lat=28.611, lng=77.231)
    farther_same_type = Unit(id=f"{failed_type}-far", type=failed_type, name="Far", lat=28.8, lng=77.4)
    closer_other_type = Unit(id="FIRE-01", type="fire", name="Closer other type", lat=28.6101, lng=77.2301)

    result = ReplanningAgent().handle_unit_unavailable(make_incident(), failed, [failed, replacement, farther_same_type, closer_other_type])

    assert result.success is True
    assert result.new_unit_id == replacement_id


def test_breakdown_does_not_use_closer_other_type_when_no_same_type_available():
    failed = Unit(id="AMB-01", type="ambulance", name="Failed", lat=28.61, lng=77.23, status="dispatched")
    closer_other_type = Unit(id="POL-01", type="police", name="Closer other type", lat=28.6101, lng=77.2301)

    result = ReplanningAgent().handle_unit_unavailable(make_incident(), failed, [failed, closer_other_type])

    assert result.success is False
    assert result.new_unit_id is None
    assert "ambulance" in result.reason


def test_breakdown_fails_when_no_same_type_unit_is_available():
    failed = Unit(id="POL-01", type="police", name="Failed", lat=28.61, lng=77.23, status="dispatched")
    busy_police = Unit(id="POL-02", type="police", name="Busy", lat=28.611, lng=77.231, status="busy")

    result = ReplanningAgent().handle_unit_unavailable(make_incident(), failed, [failed, busy_police])

    assert result.success is False
    assert result.new_unit_id is None
