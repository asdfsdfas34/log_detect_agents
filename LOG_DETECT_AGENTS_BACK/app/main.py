"""FastAPI entrypoint for 장애 예방 AI backend."""

from uuid import uuid4

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.db.scenario_store import (
    approve_result,
    fetch_exception_registry,
    fetch_knowledge_cards,
    normalize_log_text,
    register_exception,
    run_detection_pipeline,
)
from app.db.chroma_store import find_similar_pattern_clusters, save_pattern_cluster
from app.db.sqlite_store import (
    delete_recommendation_result,
    fetch_latest_recommendation_results,
    fetch_service_names,
    save_recommendation_result,
)
from app.graph.engine import build_graph
from app.state import Scope, SharedState, create_initial_state

app = FastAPI(title="Failure Prevention AI Backend", version="0.2.0")

origins = ["http://localhost:5173", "http://127.0.0.1:5173"]

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
    goal: str = Field(
        default="service log anomaly investigation", description="Analysis goal"
    )
    scope: Scope | None = Field(
        default=None, description="Optional detailed analysis scope"
    )
    save_to_chromadb: bool = Field(
        default=False, description="Persist final answer to ChromaDB"
    )


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


class RecommendationSaveRequest(BaseModel):
    """Request body for explicit recommendation history persistence."""

    request_id: str = ""
    service_name: str
    goal: str = ""
    executive_summary: str = ""
    recommendation: str
    recommended_actions: list[dict] = Field(default_factory=list)
    verification_steps: list[str] = Field(default_factory=list)
    evidence_bundle: dict = Field(default_factory=dict)
    risk_score: int | None = None
    confidence: str | None = None


class FingerprintRecommendationRequest(BaseModel):
    """Request body for rerunning downstream recommendation agents for one fingerprint."""

    service_name: str
    fingerprint: str


class ServiceListResponse(BaseModel):
    services: list[str]


class RecommendationHistoryResponse(BaseModel):
    recommendations: list[dict]


class KnowledgeCardListResponse(BaseModel):
    knowledge_cards: list[dict]


class ExceptionRegistryResponse(BaseModel):
    exceptions: list[dict]


def _pattern_cluster_context(
    *,
    service_name: str,
    fingerprint: str,
    message: str,
    log_level: str,
    stacktrace: str = "",
) -> str:
    normalized_message = normalize_log_text(message)
    return "\n".join(
        [
            f"service={service_name}",
            f"fingerprint={fingerprint}",
            f"log_level={log_level}",
            f"normalized_message={normalized_message}",
            f"context={stacktrace or message}",
        ]
    )


def _enrich_pattern_clusters(
    *, service_name: str, fingerprints: list[dict], n_results: int = 5
) -> list[dict]:
    enriched: list[dict] = []
    for item in fingerprints:
        fingerprint = str(item.get("fingerprint", ""))
        message = str(item.get("message", ""))
        log_level = str(item.get("log_level", ""))
        stacktrace = str(item.get("stacktrace", ""))
        context = _pattern_cluster_context(
            service_name=service_name,
            fingerprint=fingerprint,
            message=message,
            log_level=log_level,
            stacktrace=stacktrace,
        )
        similar_clusters = [
            match
            for match in find_similar_pattern_clusters(
                query=context, n_results=n_results + 1
            )
            if match.get("id") != f"{service_name}:{fingerprint}"
        ][:n_results]
        semantic_similarity = (
            round(float(similar_clusters[0]["similarity"]) * 100)
            if similar_clusters and similar_clusters[0].get("similarity") is not None
            else 0
        )
        save_pattern_cluster(
            doc_id=f"{service_name}:{fingerprint}",
            text=context,
            metadata={
                "service_name": service_name,
                "fingerprint": fingerprint,
                "log_level": log_level,
                "normalized_message": normalize_log_text(message),
                "occurrence_count": int(item.get("occurrence_count") or 0),
            },
        )
        enriched.append(
            {
                "cluster": fingerprint,
                "count": item["occurrence_count"],
                "message": message,
                "log_level": log_level,
                "semantic_similarity": semantic_similarity,
                "similar_clusters": similar_clusters,
            }
        )
    return enriched


def build_generated_answer(
    *,
    recommendation: dict,
    message: str = "",
    stacktrace: str = "",
    occurrence_count: int | None = None,
    log_level: str = "",
    risk_level: str = "",
    risk_score: int | None = None,
) -> str:
    """Build a detailed recommendation answer from the selected log evidence."""
    lines = [
        "Log Evidence Analysis",
        f"- Error Message: {message or '-'}",
        f"- Level: {log_level or '-'}",
    ]
    if occurrence_count is not None:
        lines.append(f"- Occurrence Count: {occurrence_count}")
    if risk_score is not None:
        lines.append(f"- Risk: {risk_level or '-'} ({risk_score})")
    lines.extend(
        [
            f"- Stack Trace: {stacktrace or '-'}",
            "",
            "Assessment",
            f"- Probable Cause: {recommendation.get('cause') or '-'}",
            (
                "- Detail: The message and stack trace above should be used to "
                "confirm the failing component, volatile identifiers, and repeated "
                "request context before applying the fix."
            ),
            "",
            "Recommended Action",
            f"- {recommendation.get('recommendation') or '-'}",
        ]
    )
    return "\n".join(lines)


@app.get("/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "model": settings.openai_model,
        "stub_mode": str(settings.llm_stub_mode),
    }


@app.get("/services", response_model=ServiceListResponse)
def list_services() -> ServiceListResponse:
    return ServiceListResponse(services=fetch_service_names())


@app.get("/recommendations", response_model=RecommendationHistoryResponse)
def list_recommendations(
    service_name: str | None = None, limit: int = 20
) -> RecommendationHistoryResponse:
    """Return saved recommendation results, newest first."""
    service_names = [service_name] if service_name else None
    return RecommendationHistoryResponse(
        recommendations=fetch_latest_recommendation_results(
            service_names=service_names, limit=limit
        )
    )


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
    if scenario["fingerprints"]:
        result["evidence"]["clusters"] = _enrich_pattern_clusters(
            service_name=req.service_name, fingerprints=scenario["fingerprints"]
        )
        result["evidence"]["anomalies"] = scenario["anomalies"]
        result["evidence"]["stack_traces"] = [
            item["stacktrace"]
            for item in scenario["fingerprints"]
            if item["stacktrace"]
        ]
        result["assessment"]["risk_score"] = scenario["summary"]["risk_score"]
        result["assessment"]["confidence"] = (
            "high" if scenario["summary"]["risk_score"] >= 70 else "mid"
        )
        result["assessment"]["rationale"] = [
            f"Risk Level: {scenario['summary']['risk_level']}",
            f"Detection Status: {scenario['summary']['detection_status']}",
        ]
        # Keep RecommendationAgent's LLM+RAG output as the final recommendation.
        # The deterministic scenario pipeline enriches evidence/assessment only; it
        # must not overwrite final recommended_actions, verification_steps, or
        # generated_answer.
        final_bundle = result["final"].get("evidence_bundle")
        if isinstance(final_bundle, dict):
            final_bundle["scenario_detection"] = scenario
        else:
            result["final"]["evidence_bundle"] = {"scenario_detection": scenario}

    result["final"]["saved_recommendation_id"] = None
    return AnalyzeResponse(result=result)


@app.post("/recommendations/save")
def save_recommendation(req: RecommendationSaveRequest) -> dict[str, int | str]:
    """Persist a generated recommendation only after explicit user action."""
    saved_id = save_recommendation_result(
        request_id=req.request_id,
        service_name=req.service_name,
        goal=req.goal,
        executive_summary=req.executive_summary,
        recommendation=req.recommendation,
        recommended_actions=req.recommended_actions,
        verification_steps=req.verification_steps,
        evidence_bundle=req.evidence_bundle,
        risk_score=req.risk_score,
        confidence=req.confidence,
    )
    return {"status": "saved", "id": saved_id}


@app.delete("/recommendations/{recommendation_id}")
def delete_recommendation(recommendation_id: int) -> dict[str, int | str]:
    """Delete one saved recommendation history item."""
    if delete_recommendation_result(recommendation_id=recommendation_id):
        return {"status": "deleted", "id": recommendation_id}
    return {"status": "not_found", "id": recommendation_id}


@app.post("/recommendations/fingerprint", response_model=AnalyzeResponse)
def recommend_for_fingerprint(req: FingerprintRecommendationRequest) -> AnalyzeResponse:
    """Build a recommendation preview for one selected fingerprint without persisting it."""
    scenario = run_detection_pipeline(req.service_name)
    selected = next(
        (
            item
            for item in scenario["fingerprints"]
            if item["fingerprint"] == req.fingerprint
        ),
        None,
    )
    selected_recommendation = next(
        (
            item
            for item in scenario.get("recommendations", [])
            if item["fingerprint"] == req.fingerprint
        ),
        scenario["recommendation"],
    )
    selected_impact = next(
        (
            item
            for item in scenario.get("impacts", [])
            if item["fingerprint"] == req.fingerprint
        ),
        {"risk_score": 0, "risk_level": "Low", "detected": False},
    )

    state = create_initial_state(
        goal=f"selected fingerprint recommendation: {req.fingerprint}",
        scope={
            "systems": [req.service_name],
            "time_range": {"from": "", "to": ""},
            "filters": {"fingerprint": req.fingerprint},
        },
        request_id=uuid4().hex,
    )
    # Mark only the downstream agents requested by cluster selection as executed.
    state["decisions"]["agents_run"] = [
        "ImpactEvaluationAgent",
        "KnowledgeBaseRAGAgent",
        "RecommendationAgent",
    ]
    state["decisions"]["skipped_agents"] = [
        "OrchestratorAgent",
        "LogCollectorAgent",
        "LogAnalysisAgent",
        "AnomalyDetectionAgent",
        "SourceCodeAnalysisAgent",
    ]
    if selected:
        state["evidence"]["clusters"] = _enrich_pattern_clusters(
            service_name=req.service_name, fingerprints=[selected]
        )
        state["evidence"]["stack_traces"] = [selected["stacktrace"]]
    state["assessment"]["risk_score"] = selected_impact["risk_score"]
    state["assessment"]["confidence"] = (
        "high" if selected_recommendation["confidence"] == "HIGH" else "mid"
    )
    state["assessment"]["rationale"] = [
        f"Selected Fingerprint: {req.fingerprint}",
        f"Risk Level: {selected_impact['risk_level']}",
    ]
    state["final"]["executive_summary"] = selected_recommendation["cause"]
    state["final"]["recommended_actions"] = [
        {
            "priority": selected_recommendation["confidence"],
            "action": selected_recommendation["recommendation"],
            "owner": "service-owner",
        }
    ]
    state["final"]["verification_steps"] = [
        f"Review logs grouped by {req.fingerprint}",
        "Apply the recommended fix and monitor the fingerprint count",
    ]
    generated_answer = build_generated_answer(
        recommendation=selected_recommendation,
        message=selected["message"] if selected else "",
        stacktrace=selected["stacktrace"] if selected else "",
        occurrence_count=selected["occurrence_count"] if selected else None,
        log_level=selected["log_level"] if selected else "",
        risk_level=selected_impact["risk_level"],
        risk_score=selected_impact["risk_score"],
    )
    state["final"]["generated_answer"] = generated_answer
    state["final"]["evidence_bundle"] = {
        "selected_fingerprint": req.fingerprint,
        "recommendation": selected_recommendation,
        "impact": selected_impact,
    }
    state["final"]["saved_recommendation_id"] = None
    return AnalyzeResponse(result=state)


@app.get("/exceptions", response_model=ExceptionRegistryResponse)
def list_exceptions(
    fingerprint: str | None = None, limit: int = 20
) -> ExceptionRegistryResponse:
    """Return registered exception fingerprints, newest first."""
    return ExceptionRegistryResponse(
        exceptions=fetch_exception_registry(fingerprint=fingerprint, limit=limit)
    )


@app.get("/knowledge-cards", response_model=KnowledgeCardListResponse)
def list_knowledge_cards(
    fingerprint: str | None = None, limit: int = 20
) -> KnowledgeCardListResponse:
    """Return approved Knowledge Cards, newest first."""
    return KnowledgeCardListResponse(
        knowledge_cards=fetch_knowledge_cards(fingerprint=fingerprint, limit=limit)
    )


@app.post("/exceptions")
def create_exception(req: ExceptionRegisterRequest) -> dict[str, str]:
    """Register a fingerprint ignore rule for SC-006."""
    register_exception(req.fingerprint, req.reason)
    return {"status": "registered", "fingerprint": req.fingerprint}


@app.post("/approvals")
def approve_recommendation(req: ApprovalRequest) -> dict[str, str]:
    """Approve a recommendation and create a Knowledge Card for SC-007."""
    card_id = approve_result(
        req.fingerprint, req.cause, req.recommendation, req.action, req.confidence
    )
    return {"result": "approved", "card_id": card_id}
