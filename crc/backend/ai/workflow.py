from typing import TypedDict

from .incident_analyzer import IncidentAnalyzer
from .schemas import AIIncidentResponse, AnalyzeIncidentRequest, DispatchRecord, IncidentAnalysis
from .tools import dispatch_unit, get_nearest_available_unit

try:
    from langgraph.graph import END, START, StateGraph
except ImportError:
    StateGraph = None


class WorkflowState(TypedDict, total=False):
    request: AnalyzeIncidentRequest
    analysis: IncidentAnalysis
    incident_id: str
    dispatches: list[DispatchRecord]
    status: str


class CrisisResponseWorkflow:
    def __init__(self, analyzer=None):
        self.analyzer = analyzer or IncidentAnalyzer()
        self.graph = self._build_graph() if StateGraph else None

    def _build_graph(self):
        graph = StateGraph(WorkflowState)
        graph.add_node("incident_received", lambda state: state)
        graph.add_node("analyze_incident", self._analyze_node)
        graph.add_edge(START, "incident_received")
        graph.add_edge("incident_received", "analyze_incident")
        graph.add_edge("analyze_incident", END)
        return graph.compile()

    async def _analyze_node(self, state: WorkflowState) -> WorkflowState:
        state["analysis"] = await self.analyzer.analyze(
            state["request"].description,
            state["request"].location.name,
        )
        return state

    async def run(self, request: AnalyzeIncidentRequest) -> AIIncidentResponse:
        from ..models.incident import IncidentCreate
        from ..services import dispatch_service

        if self.graph:
            state = await self.graph.ainvoke({"request": request})
            analysis = state["analysis"]
        else:
            analysis = await self.analyzer.analyze(request.description, request.location.name)
        incident = dispatch_service.create_ai_incident_record(
            IncidentCreate(
                type=dispatch_service.map_analysis_type(analysis.incident_type),
                severity=analysis.severity.lower(),
                lat=request.location.lat,
                lng=request.location.lng,
                location_name=request.location.name or analysis.location or "Unknown location",
                description=request.description,
            ),
            analysis,
        )

        dispatches = []
        for service in analysis.required_services:
            candidate = get_nearest_available_unit.invoke({
                "service": service,
                "lat": request.location.lat,
                "lng": request.location.lng,
            })
            if not candidate.get("available"):
                dispatches.append(DispatchRecord(service=service, status="PENDING", message=candidate["message"]))
                continue
            result = dispatch_unit.invoke({
                "incident_id": incident.id,
                "service": service,
                "unit_id": candidate["unit_id"],
            })
            if result.get("status") != "DISPATCHED":
                dispatches.append(DispatchRecord(service=service, status="PENDING", message=result.get("message")))
                continue
            dispatches.append(DispatchRecord(service=service, status="DISPATCHED", **{
                key: result[key] for key in ("unit_id", "distance_km", "eta_minutes") if key in result
            }))

        dispatch_service.finalize_ai_incident(incident, dispatches, analysis.reasoning)
        status = "DISPATCHED" if any(d.status == "DISPATCHED" for d in dispatches) else "PENDING"
        return AIIncidentResponse(
            incident_id=incident.id,
            incident=incident.model_dump(mode="json"),
            analysis=analysis,
            dispatches=dispatches,
            status=status,
        )
