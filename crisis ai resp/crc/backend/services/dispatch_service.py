"""
Dispatch Service
-----------------
Central orchestrator that ties all four agents together.
Maintains in-memory state (units + incidents + obstructions).
"""

import json
import math
import random
from pathlib import Path
from datetime import datetime
from typing import Optional

from ..models.incident import Incident, IncidentCreate
from ..models.unit import Unit
from ..models.obstruction import Obstruction, ObstructionReport
from ..models.unit import Unit
from ..agents.dispatcher_agent import DispatcherAgent
from ..agents.resource_agent import ResourceAgent
from ..agents.replanning_agent import ReplanningAgent, ReplanResult, ReplanTrigger, ObstructionType
from . import routing_service

# ── In-memory state ────────────────────────────────────────────────────────────
_units:          list[Unit]        = []
_incidents:      list[Incident]    = []
_obstructions:   list[Obstruction] = []
_dispatch_log:   list[dict]        = []
_replan_history: list[dict]        = []
_resolved_count: int               = 0

# ── Agent instances ─────────────────────────────────────────────────────────────
_dispatcher = DispatcherAgent()
_resource    = ResourceAgent()
_replanning  = ReplanningAgent()

SERVICE_UNIT_TYPES = {
    "POLICE": "police",
    "AMBULANCE": "ambulance",
    "FIRE_RESCUE": "fire",
    "HIGHWAY_ASSISTANCE": "highway_assistance",
}


# ── Bootstrap ──────────────────────────────────────────────────────────────────
def _load_units():
    global _units
    path = Path(__file__).parent.parent / "data" / "units.json"
    data = json.loads(path.read_text())
    _units = [Unit(**d) for d in data]


_load_units()


def _log(msg: str, level: str = "info"):
    entry = {"ts": datetime.utcnow().isoformat(), "level": level, "msg": msg}
    _dispatch_log.append(entry)
    if len(_dispatch_log) > 200:
        _dispatch_log.pop(0)
    print(f"[{level.upper()}] {msg}")


def _record_replan(result: ReplanResult):
    _replan_history.append(result.to_dict())
    if len(_replan_history) > 100:
        _replan_history.pop(0)


# ── Public getters ─────────────────────────────────────────────────────────────

def get_units()          -> list[Unit]:        return _units
def get_incidents()      -> list[Incident]:    return _incidents
def get_obstructions()   -> list[Obstruction]: return _obstructions
def get_log()            -> list[dict]:        return list(reversed(_dispatch_log))
def get_replan_history() -> list[dict]:        return list(reversed(_replan_history))


def map_analysis_type(incident_type: str):
    return {
        "road_accident": "accident",
        "vehicle_breakdown": "accident",
        "unknown": "medical",
    }.get(incident_type, incident_type if incident_type in {"fire", "medical", "accident", "flood", "crime", "building", "gas"} else "medical")


def create_ai_incident_record(data: IncidentCreate, analysis) -> Incident:
    """Create the shared incident record before any AI-selected tool dispatches."""
    inc = Incident(
        type=data.type,
        severity=data.severity,
        lat=data.lat,
        lng=data.lng,
        location_name=data.location_name,
        description=data.description or "",
    )
    inc = _dispatcher.classify(inc)
    _incidents.append(inc)
    _log(f"AI analysis recorded for #{inc.id}: {analysis.incident_type} / {analysis.severity}", "info")
    return inc


def find_nearest_for_service(service: str, lat: float, lng: float) -> Optional[Unit]:
    """Return an exact service match; geographic selection stays deterministic."""
    unit_type = SERVICE_UNIT_TYPES.get(service.upper())
    candidates = [u for u in _units if u.status == "available" and u.type == unit_type]
    if not candidates:
        return None
    return min(candidates, key=lambda u: _straight_dist(u.lat, u.lng, lat, lng))


def dispatch_selected_unit(incident_id: str, service: str, unit_id: str) -> dict:
    """Validate and reserve a real unit selected by a LangChain tool."""
    inc = next((item for item in _incidents if item.id == incident_id), None)
    unit = next((item for item in _units if item.id == unit_id), None)
    expected_type = SERVICE_UNIT_TYPES.get(service.upper())
    if not inc or not unit:
        return {"status": "FAILED", "message": "Incident or unit not found."}
    if unit.status != "available" or unit.type != expected_type:
        return {"status": "FAILED", "message": f"{unit_id} is unavailable for {service}."}

    distance = _straight_dist(unit.lat, unit.lng, inc.lat, inc.lng)
    eta = _straight_eta(unit.lat, unit.lng, inc.lat, inc.lng)
    unit.status = "dispatched"
    unit.assigned_incident = inc.id
    inc.assigned_unit = inc.assigned_unit or unit.id
    inc.status = "dispatched"
    _log(f"AI dispatched {unit.id} ({service}) -> #{inc.id} | {distance:.1f} km", "ok")
    return {
        "status": "DISPATCHED",
        "unit_id": unit.id,
        "distance_km": distance,
        "eta_minutes": eta,
    }


def update_incident_status(incident_id: str, status: str) -> dict:
    inc = next((item for item in _incidents if item.id == incident_id), None)
    if not inc or status not in {"pending", "dispatched", "on_scene", "resolved"}:
        return {"success": False, "message": "Incident or status is invalid."}
    inc.status = status
    return {"success": True, "incident_id": incident_id, "status": status}


def finalize_ai_incident(incident: Incident, dispatches: list, reasoning: str):
    incident.required_services = [dispatch.service for dispatch in dispatches]
    incident.dispatches = [dispatch.model_dump() for dispatch in dispatches]
    incident.ai_reasoning = reasoning
    incident.ai_analysis = {"required_services": incident.required_services, "reasoning": reasoning}
    dispatched = [d for d in dispatches if d.status == "DISPATCHED"]
    if dispatched:
        incident.eta_minutes = min(d.eta_minutes for d in dispatched if d.eta_minutes is not None)
        incident.route_distance_km = min(d.distance_km for d in dispatched if d.distance_km is not None)
    if not dispatched:
        incident.status = "pending"
        _log(f"No AI-selected units available for #{incident.id} — queued PENDING", "warn")


def get_stats() -> dict:
    active = [i for i in _incidents if i.status != "resolved"]
    return {
        "active_incidents": len(active),
        "pending":          sum(1 for i in active if i.status == "pending"),
        "dispatched":       sum(1 for i in active if i.status == "dispatched"),
        "on_scene":         sum(1 for i in active if i.status == "on_scene"),
        "resolved_total":   _resolved_count,
        "replan_count":     len(_replan_history),
        "active_obstructions": sum(1 for o in _obstructions if not o.cleared),
        "units":            _resource.availability_report(_units),
        "warnings":         _replanning.detect_conflicts(_units, _incidents),
    }


# ── Core incident creation ─────────────────────────────────────────────────────

async def create_incident(data: IncidentCreate) -> Incident:
    inc = Incident(
        type=data.type, severity=data.severity,
        lat=data.lat, lng=data.lng,
        location_name=data.location_name,
        description=data.description or "",
    )

    # Agent 1: classify
    inc = _dispatcher.classify(inc)
    _log(_dispatcher.summarise(inc), "info")
    _incidents.append(inc)

    # Agent 2: find unit
    preferred_types = _dispatcher.get_preferred_unit_types(inc.type)
    unit = _resource.find_nearest(inc, _units, preferred_types)
    if unit is None:
        inc.status = "pending"
        _log(f"No units available for #{inc.id} — queued PENDING", "warn")
        return inc

    # Agent 3: route
    route = await routing_service.fetch_route(unit, inc)

    unit.status = "dispatched"
    unit.assigned_incident = inc.id
    inc.status = "dispatched"
    inc.assigned_unit = unit.id
    inc.eta_minutes = route.duration_min
    inc.route_distance_km = route.distance_km

    _log(
        f"Dispatched {unit.id} → #{inc.id} | {route.distance_km:.1f} km | "
        f"ETA {route.duration_min:.0f} min | via {route.source}",
        "ok",
    )

    # Agent 4: conflict check
    for w in _replanning.detect_conflicts(_units, _incidents):
        _log(w, "warn")

    return inc


# ── Resolve ────────────────────────────────────────────────────────────────────

def resolve_incident(incident_id: str) -> Optional[Incident]:
    global _resolved_count
    inc = next((i for i in _incidents if i.id == incident_id), None)
    if not inc or inc.status == "resolved":
        return inc

    inc.status = "resolved"
    inc.resolved_at = datetime.utcnow()
    _resolved_count += 1

    if inc.assigned_unit:
        unit = next((u for u in _units if u.id == inc.assigned_unit), None)
        if unit:
            unit.status = "available"
            unit.assigned_incident = None
            unit.lat += (random.random() - 0.5) * 0.02
            unit.lng += (random.random() - 0.5) * 0.02
            _log(f"{unit.id} cleared — returning to patrol", "ok")

    _log(f"Incident #{incident_id} resolved", "ok")
    return inc


# ── Manual dispatch ────────────────────────────────────────────────────────────

async def manual_dispatch(incident_id: str) -> Optional[Incident]:
    inc = next((i for i in _incidents if i.id == incident_id and i.status == "pending"), None)
    if not inc:
        return None
    preferred_types = _dispatcher.get_preferred_unit_types(inc.type)
    unit = _resource.find_nearest(inc, _units, preferred_types)
    if not unit:
        _log(f"Manual dispatch failed for #{inc.id} — no units available", "warn")
        return inc
    route = await routing_service.fetch_route(unit, inc)
    unit.status = "dispatched"
    unit.assigned_incident = inc.id
    inc.status = "dispatched"
    inc.assigned_unit = unit.id
    inc.eta_minutes = route.duration_min
    inc.route_distance_km = route.distance_km
    _log(f"Manual dispatch: {unit.id} → #{inc.id}", "ok")
    return inc


# ── ★ REPLANNING CORE ──────────────────────────────────────────────────────────

async def report_obstruction(report: ObstructionReport) -> dict:
    """
    Called when a unit reports an obstacle on its route.

    Pipeline:
      1. Store obstruction record
      2. Ask replanning agent for a ReplanResult
      3. Call routing agent with unit's CURRENT position + avoid-point hint
      4. Update incident ETA + route
      5. Return full replan payload to the frontend
    """
    inc  = next((i for i in _incidents if i.id == report.incident_id), None)
    unit = next((u for u in _units     if u.id == report.unit_id),     None)

    if not inc or not unit:
        return {"success": False, "reason": "Incident or unit not found"}

    # Store obstruction
    obs = Obstruction(
        incident_id=report.incident_id,
        unit_id=report.unit_id,
        obstruction_type=report.obstruction_type,
        lat=report.obstruction_lat,
        lng=report.obstruction_lng,
        description=report.description or "",
    )
    _obstructions.append(obs)

    _log(
        f"⚠ OBSTRUCTION reported by {unit.id} on route to #{inc.id}: "
        f"{report.obstruction_type} near ({report.obstruction_lat:.4f}, {report.obstruction_lng:.4f})",
        "warn",
    )

    # Ask replanning agent
    obs_enum = _parse_obstruction_type(report.obstruction_type)

    if obs_enum == ObstructionType.UNIT_BREAKDOWN:
        # Unit itself is the problem → reassign to a different unit
        result = _replanning.handle_unit_unavailable(inc, unit, _units)
        return await _execute_unit_reassignment(inc, unit, result)
    else:
        # Same unit, different route
        result = _replanning.handle_obstruction(
            incident=inc, unit=unit,
            obstruction_type=obs_enum,
            obstruction_lat=report.obstruction_lat,
            obstruction_lng=report.obstruction_lng,
            current_unit_lat=report.current_unit_lat,
            current_unit_lng=report.current_unit_lng,
        )
        return await _execute_reroute(inc, unit, result,
                                      report.current_unit_lat, report.current_unit_lng,
                                      report.obstruction_lat, report.obstruction_lng)


async def trigger_manual_replan(incident_id: str,
                                 current_unit_lat: float,
                                 current_unit_lng: float) -> dict:
    """
    Dispatcher manually triggers a replan (e.g. they know about road works).
    Re-fetches the best route from the unit's current position.
    """
    inc  = next((i for i in _incidents if i.id == incident_id), None)
    unit = next((u for u in _units if u.id == (inc.assigned_unit if inc else "")), None)

    if not inc or not unit:
        return {"success": False, "reason": "Incident or assigned unit not found"}

    result = ReplanResult(
        success=True,
        trigger=ReplanTrigger.MANUAL,
        incident_id=inc.id,
        old_unit_id=unit.id,
        new_unit_id=unit.id,
        reason="Manual replan requested by dispatcher",
    )
    return await _execute_reroute(inc, unit, result,
                                   current_unit_lat, current_unit_lng,
                                   None, None)


async def replan_unit_unavailable(incident_id: str) -> dict:
    """Called when an assigned unit breaks down or is recalled."""
    inc       = next((i for i in _incidents if i.id == incident_id), None)
    old_unit  = next((u for u in _units if u.id == (inc.assigned_unit if inc else "")), None)

    if not inc or not old_unit:
        return {"success": False, "reason": "Incident or unit not found"}

    result = _replanning.handle_unit_unavailable(inc, old_unit, _units)
    return await _execute_unit_reassignment(inc, old_unit, result)


# ── Internal replan executors ──────────────────────────────────────────────────

async def _execute_reroute(
    inc: Incident,
    unit: Unit,
    result: ReplanResult,
    from_lat: float,
    from_lng: float,
    avoid_lat: Optional[float],
    avoid_lng: Optional[float],
) -> dict:
    """Fetch a new route from (from_lat, from_lng) avoiding the obstruction point."""

    # Temporarily move unit marker to its current real position for routing
    fake_unit = Unit(
        id=unit.id, type=unit.type, name=unit.name,
        lat=from_lat, lng=from_lng, status=unit.status,
    )

    try:
        route = await routing_service.fetch_route(fake_unit, inc)
        result.new_route    = route.coordinates
        result.new_eta_min  = route.duration_min
        result.new_dist_km  = route.distance_km
    except Exception as e:
        result.new_route   = [[from_lat, from_lng], [inc.lat, inc.lng]]
        result.new_eta_min = _straight_eta(from_lat, from_lng, inc.lat, inc.lng)
        result.new_dist_km = _straight_dist(from_lat, from_lng, inc.lat, inc.lng)
        result.warnings.append(f"Routing API error — using direct path: {e}")

    # Update live incident ETA
    inc.eta_minutes      = result.new_eta_min
    inc.route_distance_km = result.new_dist_km

    _log(
        f"🔄 REROUTED {unit.id} → #{inc.id} | "
        f"New ETA: {result.new_eta_min:.0f} min | "
        f"{result.new_dist_km:.1f} km | Reason: {result.reason}",
        "ok",
    )
    _record_replan(result)
    return result.to_dict()


async def _execute_unit_reassignment(
    inc: Incident,
    old_unit: Unit,
    result: ReplanResult,
) -> dict:
    """Free old unit, assign replacement, fetch new route."""
    if not result.success:
        _log(result.reason, "error")
        _record_replan(result)
        return result.to_dict()

    new_unit = next((u for u in _units if u.id == result.new_unit_id), None)
    if not new_unit:
        result.success = False
        result.reason += " (replacement unit not found in registry)"
        _record_replan(result)
        return result.to_dict()

    # Free old unit
    old_unit.status = "available"
    old_unit.assigned_incident = None

    # Assign new unit
    new_unit.status = "dispatched"
    new_unit.assigned_incident = inc.id
    inc.assigned_unit = new_unit.id

    try:
        route = await routing_service.fetch_route(new_unit, inc)
        result.new_route   = route.coordinates
        result.new_eta_min = route.duration_min
        result.new_dist_km = route.distance_km
    except Exception as e:
        result.new_route   = [[new_unit.lat, new_unit.lng], [inc.lat, inc.lng]]
        result.new_eta_min = _straight_eta(new_unit.lat, new_unit.lng, inc.lat, inc.lng)
        result.new_dist_km = _straight_dist(new_unit.lat, new_unit.lng, inc.lat, inc.lng)
        result.warnings.append(f"Routing fallback: {e}")

    inc.eta_minutes       = result.new_eta_min
    inc.route_distance_km = result.new_dist_km

    _log(
        f"🔄 REASSIGNED #{inc.id}: {old_unit.id} → {new_unit.id} | "
        f"ETA {result.new_eta_min:.0f} min | {result.reason}",
        "ok",
    )
    _record_replan(result)
    return result.to_dict()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_obstruction_type(raw: str) -> ObstructionType:
    try:
        return ObstructionType(raw)
    except ValueError:
        return ObstructionType.ROAD_BLOCKED


def _straight_dist(lat1, lng1, lat2, lng2) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat/2)**2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlng/2)**2)
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a)), 2)


def _straight_eta(lat1, lng1, lat2, lng2, speed_kmh=40.0) -> float:
    return round((_straight_dist(lat1, lng1, lat2, lng2) / speed_kmh) * 60, 1)


# ── Demo scenarios ─────────────────────────────────────────────────────────────
_DEMO_INCIDENTS = [
    IncidentCreate(type="fire",     severity="critical", lat=28.6315, lng=77.2167, location_name="Connaught Place",   description="Large commercial building fire"),
    IncidentCreate(type="medical",  severity="high",     lat=28.5705, lng=77.2429, location_name="Lajpat Nagar",      description="Multiple cardiac cases at market"),
    IncidentCreate(type="accident", severity="high",     lat=28.6562, lng=77.2410, location_name="Kashmere Gate",     description="Multi-vehicle collision on NH44"),
    IncidentCreate(type="flood",    severity="medium",   lat=28.6200, lng=77.0500, location_name="Dwarka Sector 21",  description="Waterlogging blocking roads"),
    IncidentCreate(type="crime",    severity="high",     lat=28.6800, lng=77.2200, location_name="Rohini Sector 7",   description="Armed robbery in progress"),
    IncidentCreate(type="building", severity="critical", lat=28.6000, lng=77.3500, location_name="Mayur Vihar",       description="Partial collapse of residential building"),
    IncidentCreate(type="gas",      severity="critical", lat=28.6400, lng=77.1200, location_name="Janakpuri",         description="Industrial gas pipeline rupture"),
    IncidentCreate(type="fire",     severity="high",     lat=28.6900, lng=77.1600, location_name="Pitampura",         description="Electrical fire in market"),
    IncidentCreate(type="medical",  severity="critical", lat=28.5300, lng=77.2700, location_name="Badarpur",          description="Mass food poisoning at school"),
    IncidentCreate(type="accident", severity="medium",   lat=28.6100, lng=77.3800, location_name="Noida Sector 18",   description="2-vehicle crash, minor injuries"),
]


async def run_demo(scenario: str) -> list[Incident]:
    results = []
    if scenario == "random":
        d = random.choice(_DEMO_INCIDENTS)
        results.append(await create_incident(d))
    elif scenario == "multi":
        for d in random.sample(_DEMO_INCIDENTS, 5):
            results.append(await create_incident(d))
        _log("MASS CASUALTY EVENT — 5 simultaneous incidents", "warn")
    elif scenario == "fire_spread":
        base = next(d for d in _DEMO_INCIDENTS if d.type == "fire")
        results.append(await create_incident(base))
        results.append(await create_incident(IncidentCreate(type="fire", severity="high", lat=base.lat+0.015, lng=base.lng+0.012, location_name=f"{base.location_name} — Block B", description="Fire spread to adjacent block")))
        results.append(await create_incident(IncidentCreate(type="fire", severity="medium", lat=base.lat-0.008, lng=base.lng+0.020, location_name=f"{base.location_name} — Block C", description="Smoke in third building")))
        _log("FIRE SPREAD — 3 locations affected", "warn")
    elif scenario == "flood":
        d = next(d for d in _DEMO_INCIDENTS if d.type == "flood")
        results.append(await create_incident(d))
        results.append(await create_incident(IncidentCreate(type="flood", severity="high", lat=28.5950, lng=77.0650, location_name="Dwarka Expressway", description="Rising water, vehicles stranded")))
    elif scenario == "accident_chain":
        base = next(d for d in _DEMO_INCIDENTS if d.type == "accident")
        results.append(await create_incident(IncidentCreate(type="accident", severity="critical", lat=base.lat, lng=base.lng, location_name=base.location_name, description="Pile-up — multiple casualties")))
        results.append(await create_incident(IncidentCreate(type="accident", severity="high", lat=base.lat+0.010, lng=base.lng-0.008, location_name="NH44 Km 12", description="Secondary collision")))
        results.append(await create_incident(IncidentCreate(type="medical", severity="critical", lat=base.lat+0.005, lng=base.lng+0.005, location_name="NH44 Km 11", description="Critical injuries")))
        _log("HIGHWAY PILE-UP — chain collision detected", "warn")
    return results
