"""
CRC — Crisis Response Coordinator
FastAPI Backend
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

from .models.incident import IncidentCreate
from .models.obstruction import ObstructionReport, ManualReplanRequest
from .services import dispatch_service, routing_service

app = FastAPI(
    title="Crisis Response Coordinator API",
    description="Agentic AI-powered emergency dispatch backend by QuadCoders",
    version="1.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health ─────────────────────────────────────────────────────────────────────
@app.get("/health", tags=["System"])
def health():
    return {"status": "ok", "service": "CRC Backend v1.1"}


@app.get("/stats", tags=["System"])
def get_stats():
    return dispatch_service.get_stats()


@app.get("/log", tags=["System"])
def get_log(limit: int = Query(50, ge=1, le=200)):
    return dispatch_service.get_log()[:limit]


@app.get("/replan/history", tags=["Replanning"])
def get_replan_history(limit: int = Query(50, ge=1, le=100)):
    """Full history of all replan events (reroutes, reassignments)."""
    return dispatch_service.get_replan_history()[:limit]


# ── Units ──────────────────────────────────────────────────────────────────────
@app.get("/units", tags=["Units"])
def list_units():
    return dispatch_service.get_units()


@app.get("/units/{unit_id}", tags=["Units"])
def get_unit(unit_id: str):
    unit = next((u for u in dispatch_service.get_units() if u.id == unit_id), None)
    if not unit:
        raise HTTPException(404, f"Unit {unit_id} not found")
    return unit


# ── Incidents ──────────────────────────────────────────────────────────────────
@app.get("/incidents", tags=["Incidents"])
def list_incidents(status: Optional[str] = None):
    incidents = dispatch_service.get_incidents()
    if status:
        incidents = [i for i in incidents if i.status == status]
    return incidents


@app.get("/incidents/{incident_id}", tags=["Incidents"])
def get_incident(incident_id: str):
    inc = next((i for i in dispatch_service.get_incidents() if i.id == incident_id), None)
    if not inc:
        raise HTTPException(404, f"Incident {incident_id} not found")
    return inc


@app.post("/incidents", status_code=201, tags=["Incidents"])
async def create_incident(data: IncidentCreate):
    """
    Report a new emergency.  Full 4-agent pipeline:
    Dispatcher → Resource → Routing → Replanning
    """
    return await dispatch_service.create_incident(data)


@app.post("/incidents/{incident_id}/resolve", tags=["Incidents"])
def resolve_incident(incident_id: str):
    inc = dispatch_service.resolve_incident(incident_id)
    if not inc:
        raise HTTPException(404, f"Incident {incident_id} not found")
    return inc


@app.post("/incidents/{incident_id}/dispatch", tags=["Incidents"])
async def manual_dispatch(incident_id: str):
    inc = await dispatch_service.manual_dispatch(incident_id)
    if not inc:
        raise HTTPException(404, f"Incident {incident_id} not found or not pending")
    return inc


# ── ★ REPLANNING endpoints ─────────────────────────────────────────────────────

@app.post("/incidents/{incident_id}/replan", tags=["Replanning"])
async def manual_replan(
    incident_id: str,
    current_unit_lat: float = Query(..., description="Unit's current latitude"),
    current_unit_lng: float = Query(..., description="Unit's current longitude"),
):
    """
    Dispatcher manually triggers a replan.
    Re-fetches optimal route from the unit's CURRENT position.
    """
    result = await dispatch_service.trigger_manual_replan(
        incident_id, current_unit_lat, current_unit_lng
    )
    if not result.get("success"):
        raise HTTPException(400, result.get("reason", "Replan failed"))
    return result


@app.post("/incidents/{incident_id}/unit-unavailable", tags=["Replanning"])
async def unit_unavailable(incident_id: str):
    """
    Report that the assigned unit has broken down or been recalled.
    Triggers automatic reassignment to the next best available unit.
    """
    result = await dispatch_service.replan_unit_unavailable(incident_id)
    if not result.get("success"):
        raise HTTPException(400, result.get("reason", "Reassignment failed"))
    return result


@app.post("/obstructions", tags=["Replanning"])
async def report_obstruction(report: ObstructionReport):
    """
    A unit reports an obstacle on its current route.

    Obstruction types:
    - road_blocked   — accident/debris blocking the road
    - traffic_jam    — severe congestion, ETA unacceptable
    - bridge_closed  — infrastructure closure
    - flood_water    — road submerged
    - unit_breakdown — vehicle mechanical failure (triggers reassignment)
    - hostile_crowd  — safety issue for responder

    The agent will automatically:
    1. Store the obstruction
    2. Compute an alternate route from the unit's current position
    3. Update the incident's ETA
    4. Return the new route to be drawn on the map
    """
    result = await dispatch_service.report_obstruction(report)
    if not result.get("success"):
        raise HTTPException(400, result.get("reason", "Replan failed"))
    return result


@app.get("/obstructions", tags=["Replanning"])
def list_obstructions(active_only: bool = True):
    """List all reported obstructions."""
    obs = dispatch_service.get_obstructions()
    if active_only:
        obs = [o for o in obs if not o.cleared]
    return obs


@app.delete("/obstructions/{obstruction_id}", tags=["Replanning"])
def clear_obstruction(obstruction_id: str):
    """Mark an obstruction as cleared (road reopened)."""
    obs_list = dispatch_service.get_obstructions()
    obs = next((o for o in obs_list if o.id == obstruction_id), None)
    if not obs:
        raise HTTPException(404, f"Obstruction {obstruction_id} not found")
    obs.cleared = True
    return {"cleared": True, "id": obstruction_id}


# ── Routing ────────────────────────────────────────────────────────────────────
@app.get("/route", tags=["Routing"])
async def get_route(
    from_lat: float = Query(...),
    from_lng: float = Query(...),
    to_lat:   float = Query(...),
    to_lng:   float = Query(...),
):
    route = await routing_service.fetch_route_by_coords(from_lat, from_lng, to_lat, to_lng)
    return route.to_dict()


# ── Replanning endpoints ───────────────────────────────────────────────────────

@app.post("/incidents/{incident_id}/obstruction", tags=["Replanning"])
async def report_obstruction(incident_id: str, report: ObstructionReport):
    """
    Unit reports an obstacle on its active route.

    Obstruction types:
      road_blocked   → accident / debris blocking road
      traffic_jam    → severe congestion, ETA unacceptable
      bridge_closed  → infrastructure closure
      flood_water    → road submerged
      unit_breakdown → vehicle mechanical failure (triggers reassignment)
      hostile_crowd  → safety risk for responder

    The replanning agent:
      1. Records the obstruction point
      2. Fetches a fresh route from the unit's CURRENT position
      3. If unit_breakdown → reassigns to next nearest available unit
      4. Returns new route + updated ETA
    """
    report.incident_id = incident_id
    result = await dispatch_service.report_obstruction(report)
    if not result.get("success"):
        raise HTTPException(400, result.get("reason", "Replan failed"))
    return result


@app.post("/incidents/{incident_id}/replan", tags=["Replanning"])
async def manual_replan(incident_id: str, body: ManualReplanRequest):
    """
    Dispatcher manually triggers a route replan.
    Useful when road works or new closures are known before the unit reports them.
    """
    result = await dispatch_service.trigger_manual_replan(
        incident_id, body.current_unit_lat, body.current_unit_lng
    )
    if not result.get("success"):
        raise HTTPException(400, result.get("reason", "Replan failed"))
    return result


@app.post("/incidents/{incident_id}/unit-breakdown", tags=["Replanning"])
async def unit_breakdown(incident_id: str):
    """Assigned unit has broken down — automatically reassign to next nearest unit."""
    result = await dispatch_service.replan_unit_unavailable(incident_id)
    if not result.get("success"):
        raise HTTPException(400, result.get("reason", "No replacement unit available"))
    return result


@app.get("/replan-history", tags=["Replanning"])
def get_replan_history(limit: int = Query(20, ge=1, le=100)):
    """Return history of all replan events, newest first."""
    return dispatch_service.get_replan_history()[:limit]


@app.get("/obstructions", tags=["Replanning"])
def list_obstructions(active_only: bool = True):
    """List reported road obstructions."""
    obs = dispatch_service.get_obstructions()
    return [o for o in obs if not o.cleared] if active_only else obs


# ── Demo ───────────────────────────────────────────────────────────────────────
VALID_SCENARIOS = ["random", "multi", "fire_spread", "flood", "accident_chain"]


@app.post("/demo/{scenario}", tags=["Demo"])
async def run_demo(scenario: str):
    if scenario not in VALID_SCENARIOS:
        raise HTTPException(400, f"Choose from: {VALID_SCENARIOS}")
    incidents = await dispatch_service.run_demo(scenario)
    return {"scenario": scenario, "incidents_created": len(incidents), "incidents": incidents}
