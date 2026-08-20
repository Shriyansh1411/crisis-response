"""
Dispatcher Agent
----------------
Analyses incoming emergency incident reports, classifies
the incident type, assigns a numeric priority score, and
determines which unit type(s) should respond.
"""

from typing import Tuple
from ..models.incident import Incident, IncidentType


# Priority scoring matrix: (severity, type) → score (higher = more urgent)
SEVERITY_SCORES = {"critical": 100, "high": 70, "medium": 40, "low": 15}

TYPE_MULTIPLIERS: dict[IncidentType, float] = {
    "fire":     1.4,
    "building": 1.4,
    "gas":      1.5,
    "medical":  1.3,
    "accident": 1.2,
    "crime":    1.1,
    "flood":    1.0,
}

# Which unit type is preferred for each incident type
UNIT_PREFERENCE: dict[IncidentType, list[str]] = {
    "fire":     ["fire", "ambulance"],
    "medical":  ["ambulance", "police"],
    "accident": ["ambulance", "fire", "police"],
    "flood":    ["police", "ambulance"],
    "crime":    ["police", "ambulance"],
    "building": ["fire", "ambulance", "police"],
    "gas":      ["fire", "police"],
}


class DispatcherAgent:
    """
    Step 1 of the agent pipeline.
    Understands the report, classifies the incident and assigns a priority score.
    """

    def classify(self, incident: Incident) -> Incident:
        """
        Enrich the incident with:
        - priority_score: numeric urgency value
        Returns the mutated incident.
        """
        base = SEVERITY_SCORES.get(incident.severity, 40)
        multiplier = TYPE_MULTIPLIERS.get(incident.type, 1.0)
        incident.priority_score = int(base * multiplier)
        return incident

    def get_preferred_unit_types(self, incident_type: IncidentType) -> list[str]:
        """Return ordered list of preferred unit types for this incident."""
        return UNIT_PREFERENCE.get(incident_type, ["police"])

    def summarise(self, incident: Incident) -> str:
        """Return a human-readable dispatch brief."""
        return (
            f"[DISPATCH BRIEF] Incident #{incident.id} | "
            f"Type: {incident.type.upper()} | "
            f"Severity: {incident.severity.upper()} | "
            f"Priority Score: {incident.priority_score} | "
            f"Location: {incident.location_name} ({incident.lat:.4f}, {incident.lng:.4f})"
        )
