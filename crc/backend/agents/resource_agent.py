"""
Resource Allocation Agent
--------------------------
Finds available emergency units, checks availability,
and selects the best unit(s) to respond to an incident.
Uses haversine distance to compute proximity.
"""

import math
from typing import Optional
from ..models.unit import Unit
from ..models.incident import Incident


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return great-circle distance in kilometres."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class ResourceAgent:
    """
    Step 2 of the agent pipeline.
    Finds available responders, checks availability, selects best units.
    """

    def find_nearest(
        self,
        incident: Incident,
        units: list[Unit],
        preferred_types: list[str],
    ) -> Optional[Unit]:
        """
        1. Try to find the nearest available unit of the preferred type.
        2. Fall back to any available unit if preferred type unavailable.
        Returns None only if no units are available at all.
        """
        available = [u for u in units if u.status == "available"]
        if not available:
            return None

        # Try preferred types in order
        for ptype in preferred_types:
            typed = [u for u in available if u.type == ptype]
            if typed:
                return min(
                    typed,
                    key=lambda u: _haversine(u.lat, u.lng, incident.lat, incident.lng),
                )

        # Fallback: any available unit
        return min(
            available,
            key=lambda u: _haversine(u.lat, u.lng, incident.lat, incident.lng),
        )

    def compute_distance(self, unit: Unit, incident: Incident) -> float:
        """Return km distance from unit to incident."""
        return _haversine(unit.lat, unit.lng, incident.lat, incident.lng)

    def estimate_eta(self, distance_km: float, avg_speed_kmh: float = 40.0) -> float:
        """Estimate ETA in minutes given distance and average speed."""
        return round((distance_km / avg_speed_kmh) * 60, 1)

    def availability_report(self, units: list[Unit]) -> dict:
        """Return a summary of fleet availability."""
        total = len(units)
        available = sum(1 for u in units if u.status == "available")
        dispatched = sum(1 for u in units if u.status == "dispatched")
        busy = sum(1 for u in units if u.status == "busy")
        return {
            "total": total,
            "available": available,
            "dispatched": dispatched,
            "busy": busy,
            "utilisation_pct": round((1 - available / total) * 100, 1) if total else 0,
        }
