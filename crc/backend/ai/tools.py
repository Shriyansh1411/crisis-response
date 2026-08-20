from langchain_core.tools import tool


@tool
def get_nearest_available_unit(service: str, lat: float, lng: float) -> dict:
    """Find the nearest available unit for a service using backend distance logic."""
    from ..services import dispatch_service

    unit = dispatch_service.find_nearest_for_service(service, lat, lng)
    if unit is None:
        return {"available": False, "service": service, "message": "No matching unit is available."}
    return {"available": True, "service": service, "unit_id": unit.id, "name": unit.name}


@tool
def dispatch_unit(incident_id: str, service: str, unit_id: str) -> dict:
    """Dispatch a backend-validated unit; never accepts invented unit IDs."""
    from ..services import dispatch_service

    return dispatch_service.dispatch_selected_unit(incident_id, service, unit_id)


@tool
def update_incident_status(incident_id: str, status: str) -> dict:
    """Update status through the existing dispatch service."""
    from ..services import dispatch_service

    return dispatch_service.update_incident_status(incident_id, status)


TOOLS = [get_nearest_available_unit, dispatch_unit, update_incident_status]
