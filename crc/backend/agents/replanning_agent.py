"""
Replanning Agent
-----------------
Monitors active dispatches and incident queue.

Handles four replanning triggers:
  1. Road obstruction reported mid-route  → fetch alternate route
  2. Unit breakdown / unavailability      → reassign to next nearest unit
  3. Higher-priority incident appears     → pull unit from lower-priority job
  4. Queue drift detection                → reprioritize pending incidents

Each trigger produces a ReplanResult describing what changed and why.
"""

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from ..models.incident import Incident
from ..models.unit import Unit


# ── Obstruction types ──────────────────────────────────────────────────────────
class ObstructionType(str, Enum):
    ROAD_BLOCKED   = "road_blocked"    # accident/debris blocking the road
    TRAFFIC_JAM    = "traffic_jam"     # severe congestion, ETA unacceptable
    BRIDGE_CLOSED  = "bridge_closed"   # infrastructure closure
    FLOOD_WATER    = "flood_water"     # road submerged
    UNIT_BREAKDOWN = "unit_breakdown"  # vehicle mechanical failure
    HOSTILE_CROWD  = "hostile_crowd"   # safety issue for responder


# ── Replan triggers ────────────────────────────────────────────────────────────
class ReplanTrigger(str, Enum):
    OBSTRUCTION      = "obstruction"       # mid-route obstacle
    UNIT_UNAVAILABLE = "unit_unavailable"  # assigned unit broke down / recalled
    PRIORITY_BUMP    = "priority_bump"     # higher-severity incident needs this unit
    MANUAL           = "manual"            # dispatcher clicked "replan"


# ── Result object ─────────────────────────────────────────────────────────────
@dataclass
class ReplanResult:
    success:        bool
    trigger:        ReplanTrigger
    incident_id:    str
    old_unit_id:    Optional[str]           = None
    new_unit_id:    Optional[str]           = None
    old_route:      list[list[float]]       = field(default_factory=list)
    new_route:      list[list[float]]       = field(default_factory=list)
    new_eta_min:    Optional[float]         = None
    new_dist_km:    Optional[float]         = None
    reason:         str                     = ""
    timestamp:      str                     = field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )
    warnings:       list[str]               = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "success":      self.success,
            "trigger":      self.trigger,
            "incident_id":  self.incident_id,
            "old_unit_id":  self.old_unit_id,
            "new_unit_id":  self.new_unit_id,
            "new_route":    self.new_route,
            "new_eta_min":  self.new_eta_min,
            "new_dist_km":  self.new_dist_km,
            "reason":       self.reason,
            "timestamp":    self.timestamp,
            "warnings":     self.warnings,
        }


# ── Helpers ────────────────────────────────────────────────────────────────────
def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(dlng / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _estimate_eta(dist_km: float, speed_kmh: float = 40.0) -> float:
    return round((dist_km / speed_kmh) * 60, 1)


# ── Replanning Agent ───────────────────────────────────────────────────────────
class ReplanningAgent:
    """
    Step 4 of the agent pipeline.
    Detects new events, re-routes vehicles, reprioritizes incidents.
    """

    # ── Trigger 1: mid-route obstruction ──────────────────────────────────────
    def handle_obstruction(
        self,
        incident: Incident,
        unit: Unit,
        obstruction_type: ObstructionType,
        obstruction_lat: float,
        obstruction_lng: float,
        current_unit_lat: float,
        current_unit_lng: float,
    ) -> ReplanResult:
        """
        Called when a unit reports an obstacle on its current route.

        Strategy:
        - Record the obstruction point so the routing agent can avoid it.
        - Return a ReplanResult flagging that a new route is needed from
          the unit's CURRENT position (not its original base).
        - The dispatch_service will call routing_agent.get_route() with
          the waypoint-avoidance hint embedded.

        Returns a ReplanResult (route filled in by dispatch_service after
        calling the routing agent with the avoid-point hint).
        """
        dist_remaining = _haversine(
            current_unit_lat, current_unit_lng, incident.lat, incident.lng
        )
        eta_remaining = _estimate_eta(dist_remaining)

        reason = (
            f"{obstruction_type.value.replace('_', ' ').title()} reported "
            f"near ({obstruction_lat:.4f}, {obstruction_lng:.4f}). "
            f"Unit {unit.id} currently {dist_remaining:.1f} km from scene. "
            f"Requesting alternate route."
        )

        return ReplanResult(
            success=True,
            trigger=ReplanTrigger.OBSTRUCTION,
            incident_id=incident.id,
            old_unit_id=unit.id,
            new_unit_id=unit.id,          # same unit, new path
            new_eta_min=eta_remaining,    # will be updated after reroute
            new_dist_km=dist_remaining,
            reason=reason,
            warnings=[f"Obstruction at ({obstruction_lat:.4f}, {obstruction_lng:.4f}) — avoid point flagged"],
        )

    # ── Trigger 2: unit breakdown / unavailability ─────────────────────────────
    def handle_unit_unavailable(
        self,
        incident: Incident,
        failed_unit: Unit,
        all_units: list[Unit],
    ) -> ReplanResult:
        """
        The assigned unit broke down or was recalled.
        Find the next best available unit to take over.
        """
        available = [
            u for u in all_units
            if u.status == "available" and u.id != failed_unit.id
        ]

        if not available:
            return ReplanResult(
                success=False,
                trigger=ReplanTrigger.UNIT_UNAVAILABLE,
                incident_id=incident.id,
                old_unit_id=failed_unit.id,
                reason=f"{failed_unit.id} unavailable and NO replacement units free.",
                warnings=["CRITICAL: No units available for reassignment"],
            )

        # Prefer same type, then nearest
        same_type = [u for u in available if u.type == failed_unit.type]
        pool = same_type if same_type else available
        replacement = min(
            pool,
            key=lambda u: _haversine(u.lat, u.lng, incident.lat, incident.lng),
        )
        dist = _haversine(replacement.lat, replacement.lng, incident.lat, incident.lng)
        eta  = _estimate_eta(dist)

        reason = (
            f"{failed_unit.id} is unavailable. "
            f"Reassigning to {replacement.id} "
            f"({dist:.1f} km away, ETA ~{eta:.0f} min)."
        )
        warns = [] if same_type else [
            f"No {failed_unit.type} units available — using {replacement.type} unit {replacement.id}"
        ]

        return ReplanResult(
            success=True,
            trigger=ReplanTrigger.UNIT_UNAVAILABLE,
            incident_id=incident.id,
            old_unit_id=failed_unit.id,
            new_unit_id=replacement.id,
            new_eta_min=eta,
            new_dist_km=dist,
            reason=reason,
            warnings=warns,
        )

    # ── Trigger 3: priority bump ───────────────────────────────────────────────
    def should_reassign(
        self,
        new_incident: Incident,
        current_incidents: list[Incident],
        units: list[Unit],
    ) -> Optional[tuple[str, str]]:
        """
        Determine if any dispatched unit should be pulled from a
        lower-priority job and redirected to the new incident.

        Returns (unit_id, old_incident_id) if reassignment is warranted.
        Rule: reassign only if priority gap ≥ 30 points and unit not on-scene.
        """
        available = [u for u in units if u.status == "available"]
        if available:
            return None

        dispatched_incidents = [
            i for i in current_incidents
            if i.status == "dispatched" and i.id != new_incident.id
        ]
        if not dispatched_incidents:
            return None

        lowest = sorted(dispatched_incidents, key=lambda i: i.priority_score)[0]

        if new_incident.priority_score >= lowest.priority_score + 30:
            unit = next(
                (u for u in units
                 if u.assigned_incident == lowest.id and u.status == "dispatched"),
                None,
            )
            if unit:
                return (unit.id, lowest.id)

        return None

    # ── Trigger 4: queue reprioritization ────────────────────────────────────
    def reprioritize_queue(self, incidents: list[Incident]) -> list[Incident]:
        """Return incidents sorted by urgency: status order then priority score."""
        status_order = {"pending": 0, "dispatched": 1, "on_scene": 2, "resolved": 3}
        return sorted(
            incidents,
            key=lambda i: (status_order.get(i.status, 9), -i.priority_score),
        )

    # ── Conflict detection ────────────────────────────────────────────────────
    def detect_conflicts(self, units: list[Unit], incidents: list[Incident]) -> list[str]:
        """Return human-readable warning strings for any detected conflicts."""
        warnings = []

        for inc in incidents:
            if inc.status == "pending":
                warnings.append(
                    f"Incident #{inc.id} ({inc.type.upper()}) is PENDING — no unit assigned"
                )

        for unit_type in ["ambulance", "fire", "police"]:
            typed = [u for u in units if u.type == unit_type]
            if typed and all(u.status != "available" for u in typed):
                warnings.append(
                    f"All {unit_type.upper()} units unavailable — cross-type dispatch may be needed"
                )

        return warnings

    # ── ETA degradation check ─────────────────────────────────────────────────
    def check_eta_degradation(
        self,
        incident: Incident,
        unit: Unit,
        current_unit_lat: float,
        current_unit_lng: float,
        original_eta_min: float,
        elapsed_min: float,
    ) -> Optional[str]:
        """
        Check if the remaining travel distance implies ETA is much worse than
        originally promised. Returns a warning string if so, else None.
        """
        dist_remaining = _haversine(
            current_unit_lat, current_unit_lng, incident.lat, incident.lng
        )
        eta_remaining = _estimate_eta(dist_remaining)
        expected_remaining = max(0.0, original_eta_min - elapsed_min)

        # If remaining ETA is 50% worse than expected, flag it
        if expected_remaining > 0 and eta_remaining > expected_remaining * 1.5:
            return (
                f"ETA degradation detected for {unit.id} → #{incident.id}: "
                f"expected {expected_remaining:.0f} min remaining, "
                f"now projecting {eta_remaining:.0f} min. Consider reroute."
            )
        return None
