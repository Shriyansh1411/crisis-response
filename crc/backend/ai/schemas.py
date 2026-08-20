from typing import Literal, Optional

from pydantic import BaseModel, Field


ServiceType = Literal["POLICE", "AMBULANCE", "FIRE_RESCUE", "HIGHWAY_ASSISTANCE"]
SeverityLevel = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


class IncidentLocation(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    name: Optional[str] = "Unknown location"


class IncidentAnalysis(BaseModel):
    incident_type: str = "unknown"
    location: Optional[str] = None
    severity: SeverityLevel = "MEDIUM"
    number_of_people: Optional[int] = Field(default=None, ge=0)
    injuries: bool = False
    vehicles_involved: Optional[int] = Field(default=None, ge=0)
    fire_present: bool = False
    road_blocked: bool = False
    immediate_danger: bool = False
    required_services: list[ServiceType] = Field(default_factory=list)
    reasoning: str = "Insufficient information for a more specific classification."


class AnalyzeIncidentRequest(BaseModel):
    description: str = Field(..., min_length=1)
    location: IncidentLocation


class DispatchRecord(BaseModel):
    service: ServiceType
    unit_id: Optional[str] = None
    distance_km: Optional[float] = None
    eta_minutes: Optional[float] = None
    status: Literal["DISPATCHED", "PENDING", "FAILED"]
    message: Optional[str] = None


class AIIncidentResponse(BaseModel):
    incident_id: str
    incident: Optional[dict] = None
    analysis: IncidentAnalysis
    dispatches: list[DispatchRecord] = Field(default_factory=list)
    status: str
