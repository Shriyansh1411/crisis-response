"""
Routing Service
---------------
Thin wrapper around RoutingAgent exposing an async helper
used by DispatchService.
"""

from ..agents.routing_agent import RoutingAgent, RouteResult
from ..models.unit import Unit
from ..models.incident import Incident

_agent = RoutingAgent()


async def fetch_route(unit: Unit, incident: Incident) -> RouteResult:
    return await _agent.get_route(unit, incident)


async def fetch_route_by_coords(
    from_lat: float, from_lng: float, to_lat: float, to_lng: float
) -> RouteResult:
    return await _agent.get_route_by_coords(from_lat, from_lng, to_lat, to_lng)
