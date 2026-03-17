from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid

from .incident import IncidentType


class ObstructionReport(BaseModel):
    """Submitted by a unit or dispatcher when an obstacle is detected mid-route."""
    incident_id:       str                      # which active incident is affected
    unit_id:           str                      # which unit is reporting
    obstruction_type:  str                      # road_blocked | traffic_jam | bridge_closed | flood_water | unit_breakdown | hostile_crowd
    obstruction_lat:   float = Field(..., ge=-90,  le=90)
    obstruction_lng:   float = Field(..., ge=-180, le=180)
    current_unit_lat:  float = Field(..., ge=-90,  le=90)   # unit's current position
    current_unit_lng:  float = Field(..., ge=-180, le=180)
    description:       Optional[str] = ""


class Obstruction(BaseModel):
    """Stored obstruction record."""
    id:               str = Field(default_factory=lambda: str(uuid.uuid4())[:8].upper())
    incident_id:      str
    unit_id:          str
    obstruction_type: str
    lat:              float
    lng:              float
    description:      str = ""
    created_at:       datetime = Field(default_factory=datetime.utcnow)
    cleared:          bool = False
