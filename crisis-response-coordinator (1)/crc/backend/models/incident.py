from pydantic import BaseModel, Field
from typing import Optional, Literal
from datetime import datetime
import uuid


IncidentType = Literal["fire", "medical", "accident", "flood", "crime", "building", "gas"]
SeverityLevel = Literal["critical", "high", "medium", "low"]
IncidentStatus = Literal["pending", "dispatched", "on_scene", "resolved"]


class IncidentCreate(BaseModel):
    type: IncidentType
    severity: SeverityLevel
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    location_name: str
    description: Optional[str] = ""


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8].upper())
    type: IncidentType
    severity: SeverityLevel
    lat: float
    lng: float
    location_name: str
    description: Optional[str] = ""
    status: IncidentStatus = "pending"
    assigned_unit: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    priority_score: int = 0
    eta_minutes: Optional[float] = None
    route_distance_km: Optional[float] = None


class IncidentUpdate(BaseModel):
    status: Optional[IncidentStatus] = None
    assigned_unit: Optional[str] = None
    eta_minutes: Optional[float] = None
    route_distance_km: Optional[float] = None
