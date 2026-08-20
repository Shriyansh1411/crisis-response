from pydantic import BaseModel
from typing import Optional, Literal


UnitType = Literal["ambulance", "fire", "police"]
UnitStatus = Literal["available", "dispatched", "busy", "offline"]


class Unit(BaseModel):
    id: str
    type: UnitType
    name: str
    lat: float
    lng: float
    status: UnitStatus = "available"
    assigned_incident: Optional[str] = None


class UnitStatusUpdate(BaseModel):
    status: UnitStatus
    assigned_incident: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
