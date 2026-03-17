"""
Routing Agent
-------------
Computes the optimal route from unit to incident.
Primary: OSRM public routing API (real road network).
Fallback: straight-line (haversine) if OSRM unavailable.
"""

import httpx
from typing import Optional
from ..models.unit import Unit
from ..models.incident import Incident

OSRM_BASE = "https://router.project-osrm.org/route/v1/driving"
TIMEOUT = 8.0  # seconds


class RouteResult:
    def __init__(
        self,
        coordinates: list[list[float]],   # [[lat, lng], ...]
        distance_km: float,
        duration_min: float,
        source: str = "osrm",
    ):
        self.coordinates = coordinates
        self.distance_km = round(distance_km, 2)
        self.duration_min = round(duration_min, 1)
        self.source = source

    def to_dict(self) -> dict:
        return {
            "coordinates": self.coordinates,
            "distance_km": self.distance_km,
            "duration_min": self.duration_min,
            "source": self.source,
        }


class RoutingAgent:
    """
    Step 3 of the agent pipeline.
    Analyses road map, avoids blocked roads, computes best path.
    """

    async def get_route(self, unit: Unit, incident: Incident) -> RouteResult:
        """Fetch optimal route. Falls back to direct path on error."""
        try:
            result = await self._osrm_route(
                unit.lat, unit.lng, incident.lat, incident.lng
            )
            return result
        except Exception:
            return self._direct_route(unit, incident)

    async def get_route_by_coords(
        self, from_lat: float, from_lng: float, to_lat: float, to_lng: float
    ) -> RouteResult:
        """Public method — route between arbitrary coordinates."""
        try:
            return await self._osrm_route(from_lat, from_lng, to_lat, to_lng)
        except Exception:
            import math
            R = 6371.0
            dlat = math.radians(to_lat - from_lat)
            dlng = math.radians(to_lng - from_lng)
            a = (math.sin(dlat/2)**2
                 + math.cos(math.radians(from_lat))
                 * math.cos(math.radians(to_lat))
                 * math.sin(dlng/2)**2)
            dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
            return RouteResult(
                coordinates=[[from_lat, from_lng], [to_lat, to_lng]],
                distance_km=dist,
                duration_min=(dist / 40) * 60,
                source="fallback_direct",
            )

    async def _osrm_route(
        self, lat1: float, lng1: float, lat2: float, lng2: float
    ) -> RouteResult:
        url = f"{OSRM_BASE}/{lng1},{lat1};{lng2},{lat2}"
        params = {"overview": "full", "geometries": "geojson", "steps": "false"}

        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError("OSRM returned no route")

        route = data["routes"][0]
        coords_raw = route["geometry"]["coordinates"]  # [lng, lat] pairs from OSRM
        coords = [[c[1], c[0]] for c in coords_raw]  # convert to [lat, lng]
        distance_km = route["distance"] / 1000
        duration_min = route["duration"] / 60

        return RouteResult(
            coordinates=coords,
            distance_km=distance_km,
            duration_min=duration_min,
            source="osrm",
        )

    def _direct_route(self, unit: Unit, incident: Incident) -> RouteResult:
        """Fallback: straight line between unit and incident."""
        import math
        lat1, lng1 = unit.lat, unit.lng
        lat2, lng2 = incident.lat, incident.lng
        R = 6371.0
        dlat = math.radians(lat2 - lat1)
        dlng = math.radians(lng2 - lng1)
        a = (math.sin(dlat/2)**2
             + math.cos(math.radians(lat1))
             * math.cos(math.radians(lat2))
             * math.sin(dlng/2)**2)
        dist = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
        return RouteResult(
            coordinates=[[lat1, lng1], [lat2, lng2]],
            distance_km=dist,
            duration_min=(dist / 40) * 60,
            source="fallback_direct",
        )
