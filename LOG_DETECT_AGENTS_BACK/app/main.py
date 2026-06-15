"""FastAPI entrypoint for 장애 예방 AI backend."""

from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.config import settings
from app.db.sqlite_store import fetch_service_names
from app.db.scenario_store import approve_result, register_exception, run_detection_pipeline
from app.graph.engine import build_graph
from app.state import Scope, SharedState, create_initial_state

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Failure Prevention AI Backend", version="0.2.0")

origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    """Analyze API input schema."""

    service_name: str = Field(..., min_length=1, description="Target service name")
    goal: str = Field(default="service log anomaly investigation", description="Analysis goal")
    scope: Scope | None = Field(default=None, description="Optional detailed analysis scope")
    save_to_chromadb: bool = Field(default=False, description="Persist final answer to ChromaDB")


class AnalyzeResponse(BaseModel):
    """Analyze API output schema."""

    result: SharedState


class ExceptionRegisterRequest(BaseModel):
    """Request body for fingerprint ignore registration."""

    fingerprint: str
    reason: str


class ApprovalRequest(BaseModel):
    """Request body for approved recommendation knowledge capture."""

    fingerprint: str
    cause: str
    recommendation: str
    action: str = "approved"
    confidence: str = "HIGH"


class ServiceListResponse(BaseModel):
    services: list[str]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.openai_model, "stub_mode": str(settings.llm_stub_mode)}


@app.get("/services", response_model=ServiceListResponse)
def list_services() -> ServiceListResponse:
    return ServiceListResponse(services=fetch_service_names())


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    graph = build_graph()
    effective_scope: Scope = req.scope or {
        "systems": [req.service_name],
        "time_range": {"from": "", "to": ""},
        "filters": {},
    }
    effective_scope["systems"] = [req.service_name]

    initial_state = create_initial_state(
        goal=req.goal,
        scope=effective_scope,
        request_id=uuid4().hex,
        save_to_chromadb=req.save_to_chromadb,
    )
    result = graph.invoke(initial_state)

    # Run the deterministic scenario pipeline so the demo works without an LLM.
    scenario = run_detection_pipeline(req.service_name)
    result["evidence"]["clusters"] = [
        {"cluster": item["fingerprint"], "count": item["occurrence_count"], "message": item["message"], "log_level": item["log_level"]} for item in scenario["fingerprints"]
    ]
    result["evidence"]["anomalies"] = scenario["anomalies"]
    result["evidence"]["stack_traces"] = [item["stacktrace"] for item in scenario["fingerprints"] if item["stacktrace"]]
    result["assessment"]["risk_score"] = scenario["summary"]["risk_score"]
    result["assessment"]["confidence"] = "high" if scenario["summary"]["risk_score"] >= 70 else "mid"
    result["assessment"]["rationale"] = [f"Risk Level: {scenario['summary']['risk_level']}", f"Detection Status: {scenario['summary']['detection_status']}"]
    rec = scenario["recommendation"]
    result["final"]["recommended_actions"] = [{"priority": rec["confidence"], "action": rec["recommendation"], "owner": "service-owner"}]
    result["final"]["executive_summary"] = rec["cause"]
    result["final"]["generated_answer"] = rec["recommendation"]
    result["final"]["evidence_bundle"] = scenario
    return AnalyzeResponse(result=result)


@app.post("/exceptions")
def create_exception(req: ExceptionRegisterRequest) -> dict[str, str]:
    """Register a fingerprint ignore rule for SC-006."""
    register_exception(req.fingerprint, req.reason)
    return {"status": "registered", "fingerprint": req.fingerprint}


@app.post("/approvals")
def approve_recommendation(req: ApprovalRequest) -> dict[str, str]:
    """Approve a recommendation and create a Knowledge Card for SC-007."""
    card_id = approve_result(req.fingerprint, req.cause, req.recommendation, req.action, req.confidence)
    return {"result": "approved", "card_id": card_id}
