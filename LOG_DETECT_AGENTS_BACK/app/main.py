"""FastAPI entrypoint for 장애 예방 AI backend."""

import logging
from datetime import date
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agents.knowledge_base_rag import KnowledgeBaseRAGAgent
from app.agents.pattern_rule_suggestion import PatternRuleSuggestionAgent
from app.agents.recommendation import RecommendationAgent
from app.config import settings
from app.db.chroma_store import (
    find_similar_pattern_clusters_batch,
    save_pattern_clusters,
)
from app.db.scenario_store import (
    approve_result,
    fetch_duplicate_pattern_candidates,
    fetch_exception_registry,
    fetch_knowledge_cards,
    merge_duplicate_pattern_candidate,
    normalize_log_text,
    register_exception,
    run_detection_pipeline,
    save_known_pattern,
    save_pattern_normalization_rule,
    update_duplicate_pattern_candidate_status,
)
from app.db.sqlite_store import (
    delete_recommendation_result,
    fetch_latest_recommendation_results,
    fetch_service_names,
    save_recommendation_result,
)
from app.graph.engine import build_graph
from app.langsmith_tracing import configure_langsmith, fetch_langsmith_runs
from app.state import Scope, SharedState, create_initial_state


def configure_logging() -> None:
    """Apply LOG_LEVEL to app loggers used by background analysis work."""

    level_name = settings.log_level.upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    logging.getLogger("app").setLevel(level)
    logging.getLogger("app.db.chroma_store").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)


configure_logging()
configure_langsmith()

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
        default=True, description="Persist final answer to ChromaDB"
    )
    analysis_date: date | None = Field(
        default=None, description="Only analyze service_logs from this date"
    )


class AnalyzeResponse(BaseModel):
    """Analyze API output schema."""

    result: SharedState


class ExceptionRegisterRequest(BaseModel):
    """Request body for fingerprint ignore registration."""

    fingerprint: str
    reason: str


class KnownPatternSaveRequest(BaseModel):
    """Request body for human-selected known pattern registration."""

    fingerprint: str
    category: str = "Manual"
    sub_category: str = "Known Pattern"
    cause: str
    recommendation: str
    confidence: str = "HIGH"


class PatternRuleSuggestRequest(BaseModel):
    """Request body for normalization rule suggestion."""

    cluster: str = ""
    message: str = Field(..., min_length=1)


class PatternRuleProposalResponse(BaseModel):
    """Suggested normalization rule proposal."""

    name: str
    match_regex: str
    template: str
    confidence: str
    reason: str
    sample_before: str
    sample_after: str


class PatternRuleSaveRequest(BaseModel):
    """Request body for approved normalization rule registration."""

    name: str
    match_regex: str
    template: str
    enabled: bool = True
    priority: int = 100


class DuplicatePatternCandidatesResponse(BaseModel):
    candidates: list[dict]


class ApprovalRequest(BaseModel):
    """Request body for approved recommendation knowledge capture."""

    fingerprint: str
    cause: str
    recommendation: str
    resolution_method: str = Field(
        default="", description="How the user actually resolved this case"
    )
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


class LangSmithRunsResponse(BaseModel):
    enabled: bool
    project: str
    source: str
    runs: list[dict]
    error: str | None = None


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
    *,
    service_name: str,
    fingerprints: list[dict],
    anomalies: list[dict] | None = None,
    n_results: int = 5,
) -> list[dict]:
    enriched: list[dict] = []
    anomalies_by_pattern = {
        str(item.get("pattern")): item for item in anomalies or [] if item.get("pattern")
    }
    pattern_documents: list[dict] = []
    pattern_contexts: list[dict] = []
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
        pattern_documents.append(
            {
                "doc_id": f"{service_name}:{fingerprint}",
                "text": context,
                "metadata": {
                    "service_name": service_name,
                    "fingerprint": fingerprint,
                    "log_level": log_level,
                    "normalized_message": normalize_log_text(message),
                    "occurrence_count": int(item.get("occurrence_count") or 0),
                    "pattern_status": str(item.get("pattern_status", "")),
                },
            }
        )
        pattern_contexts.append(
            {
                "item": item,
                "doc_id": f"{service_name}:{fingerprint}",
                "query": context,
            }
        )
    save_pattern_clusters(pattern_documents)
    similar_cluster_groups = find_similar_pattern_clusters_batch(
        queries=[str(item["query"]) for item in pattern_contexts],
        n_results=n_results + 1,
    )
    for index, pattern_context in enumerate(pattern_contexts):
        item = pattern_context["item"]
        similar_group = (
            similar_cluster_groups[index] if index < len(similar_cluster_groups) else []
        )
        similar_clusters = [
            match
            for match in similar_group
            if match.get("id") != pattern_context["doc_id"]
        ][:n_results]
        fingerprint = str(item.get("fingerprint", ""))
        message = str(item.get("message", ""))
        log_level = str(item.get("log_level", ""))
        stacktrace = str(item.get("stacktrace", ""))
        semantic_similarity = (
            round(float(similar_clusters[0]["similarity"]) * 100)
            if similar_clusters and similar_clusters[0].get("similarity") is not None
            else 0
        )
        anomaly = anomalies_by_pattern.get(fingerprint)
        enriched.append(
            {
                "cluster": fingerprint,
                "count": item["occurrence_count"],
                "message": message,
                "log_level": log_level,
                "stacktrace": stacktrace,
                "pattern_status": item.get("pattern_status", ""),
                "match_source": item.get("match_source", ""),
                "similar_fingerprint": item.get("similar_fingerprint", ""),
                "similarity_score": item.get("similarity_score"),
                "semantic_similarity": semantic_similarity,
                "similar_clusters": similar_clusters,
                "anomaly_detected": anomaly is not None,
                "anomaly_type": anomaly.get("anomaly_type") if anomaly else "",
                "anomaly_severity": anomaly.get("severity") if anomaly else "",
                "anomaly_reason": _anomaly_reason(anomaly) if anomaly else "",
                "anomaly_metric": anomaly.get("metric") if anomaly else {},
            }
        )
    return enriched


def _anomaly_reason(anomaly: dict | None) -> str:
    if not anomaly:
        return ""
    anomaly_type = str(anomaly.get("anomaly_type") or "")
    metric = anomaly.get("metric") if isinstance(anomaly.get("metric"), dict) else {}
    latest = metric.get("latest_count")
    baseline = metric.get("baseline_count")
    if anomaly_type in {"SPIKE", "INCREASE"}:
        return f"패턴 발생량 증가: latest={latest}, baseline={baseline}"
    if anomaly_type in {"DROP", "DECREASE"}:
        return f"패턴 발생량 감소: latest={latest}, baseline={baseline}"
    if anomaly_type == "ABSENCE":
        return f"기준선에 있던 패턴 부재: latest={latest}, baseline={baseline}"
    if anomaly_type in {"NEW_ERROR", "NEW_PATTERN", "PRESENCE"}:
        return "신규 패턴이 관측되었습니다."
    if anomaly_type == "RECURRENCE":
        return "과거 관측된 패턴이 재발했습니다."
    if anomaly_type == "SIMILAR_CASE_MATCH":
        return "유사한 승인/지식 사례와 매칭되었습니다."
    return str(anomaly.get("message") or anomaly_type or "Anomaly detected")


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


@app.get("/langsmith/runs", response_model=LangSmithRunsResponse)
def list_langsmith_runs(limit: int = 20) -> LangSmithRunsResponse:
    """Return recent LangSmith runs or local agent-flow trace events."""
    payload = fetch_langsmith_runs(limit=limit)
    return LangSmithRunsResponse(**payload)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    graph = build_graph()
    time_range = {"from": "", "to": ""}
    if req.analysis_date is not None:
        time_range = {
            "from": req.analysis_date.isoformat(),
            "to": req.analysis_date.isoformat(),
        }
    effective_scope: Scope = req.scope or {
        "systems": [req.service_name],
        "time_range": time_range,
        "filters": {},
    }
    effective_scope["systems"] = [req.service_name]
    effective_scope["time_range"] = time_range

    initial_state = create_initial_state(
        goal=req.goal,
        scope=effective_scope,
        request_id=uuid4().hex,
        save_to_chromadb=req.save_to_chromadb,
    )
    result = graph.invoke(initial_state)

    # Run deterministic scenario analysis for dashboard evidence. Final
    # recommendations are generated only through the explicit recommendation API.
    try:
        if req.analysis_date is not None:
            scenario = run_detection_pipeline(
                req.service_name, analysis_date=req.analysis_date.isoformat()
            )
        else:
            scenario = run_detection_pipeline(
                req.service_name, days_back=settings.log_lookback_days
            )
    except TypeError:
        scenario = run_detection_pipeline(req.service_name)
    except ValueError:
        scenario = {
            "fingerprints": [],
            "anomalies": [],
            "summary": {},
            "recommendation": {},
            "recommendations": [],
        }
    result["evidence"]["summary"] = scenario["summary"]
    result["evidence"]["recommendation"] = scenario["recommendation"]
    if scenario["fingerprints"]:
        result["evidence"]["clusters"] = _enrich_pattern_clusters(
            service_name=req.service_name,
            fingerprints=scenario["fingerprints"],
            anomalies=scenario.get("anomalies", []),
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
            (
                f"Analysis date: {req.analysis_date.isoformat()}"
                if req.analysis_date is not None
                else f"Recent window: {settings.log_lookback_days} days"
            ),
        ]
        result["evidence"]["known_pattern_matches"] = scenario.get(
            "recommendations", []
        )[:5]
        result["evidence"]["duplicate_pattern_candidates"] = scenario.get(
            "duplicate_pattern_candidates", []
        )
        result["evidence"]["incident_candidates"] = [
            {
                "fingerprint": scenario["recommendation"].get("fingerprint"),
                "root_cause_hint": scenario["recommendation"].get("cause", ""),
                "recommended_action_hint": scenario["recommendation"].get(
                    "recommendation", ""
                ),
                "summary": scenario["summary"],
            }
        ]

    result["final"].setdefault("evidence_bundle", {})
    if result["final"]["evidence_bundle"] is None:
        result["final"]["evidence_bundle"] = {}
    result["final"]["evidence_bundle"].update(
        {
            "summary": scenario.get("summary", {}),
            "recommendation": scenario.get("recommendation", {}),
            "scenario_detection": {
                "summary": scenario.get("summary", {}),
                "recommendation": scenario.get("recommendation", {}),
            },
            "known_pattern_summary": {
                "total_matches": len(result["evidence"].get("known_pattern_matches", [])),
                "suppressed": len(result["evidence"].get("suppressed_logs", [])),
            },
        }
    )
    result["decisions"]["skipped_agents"].append("RecommendationAgent")

    result = KnowledgeBaseRAGAgent().run(result)
    result = KnowledgeBaseRAGAgent().persist_final_answer(result)
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
    scenario = run_detection_pipeline(
        req.service_name, days_back=settings.log_lookback_days
    )
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
        "KnowledgeBaseRAGAgent",
    ]
    state["decisions"]["skipped_agents"] = [
        "OrchestratorAgent",
        "LogCollectorAgent",
        "LogAnalysisAgent",
        "AnomalyDetectionAgent",
    ]
    if selected:
        state["evidence"]["clusters"] = _enrich_pattern_clusters(
            service_name=req.service_name,
            fingerprints=[selected],
            anomalies=scenario.get("anomalies", []),
        )
        state["evidence"]["stack_traces"] = [selected["stacktrace"]]
        state["evidence"]["normalized_logs"] = [
            {
                "system": req.service_name,
                "level": selected.get("log_level", ""),
                "message": selected.get("message", ""),
                "stack_trace": selected.get("stacktrace", ""),
            }
        ]
        state["evidence"]["anomalies"] = [
            item
            for item in scenario.get("anomalies", [])
            if item.get("pattern") == req.fingerprint
        ]
    state["evidence"]["known_pattern_matches"] = [
        {
            "fingerprint": req.fingerprint,
            "cause": selected_recommendation.get("cause", ""),
            "recommendation": selected_recommendation.get("recommendation", ""),
            "confidence": selected_recommendation.get("confidence", ""),
            "sub_category": selected_recommendation.get("sub_category", ""),
        }
    ]
    state["evidence"]["incident_candidates"] = [
        {
            "fingerprint": req.fingerprint,
            "root_cause_hint": selected_recommendation.get("cause", ""),
            "recommended_action_hint": selected_recommendation.get(
                "recommendation", ""
            ),
            "impact": selected_impact,
            "selected_log": selected or {},
        }
    ]
    state["evidence"]["summary"] = scenario["summary"]
    state["evidence"]["recommendation"] = selected_recommendation
    state["rag"]["related_knowledge"] = fetch_knowledge_cards(
        fingerprint=req.fingerprint, limit=5
    )
    state["assessment"]["risk_score"] = selected_impact["risk_score"]
    state["assessment"]["confidence"] = (
        "high" if selected_recommendation["confidence"] == "HIGH" else "mid"
    )
    state["assessment"]["rationale"] = [
        f"Selected Fingerprint: {req.fingerprint}",
        f"Risk Level: {selected_impact['risk_level']}",
        f"Rule/knowledge recommendation hint: {selected_recommendation.get('recommendation', '-')}",
    ]
    state = RecommendationAgent().run(state)
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


@app.post("/known-patterns")
def create_known_pattern(req: KnownPatternSaveRequest) -> dict[str, int | str]:
    """Register a human-selected known pattern."""
    pattern_id = save_known_pattern(
        fingerprint=req.fingerprint,
        category=req.category,
        sub_category=req.sub_category,
        cause=req.cause,
        recommendation=req.recommendation,
        confidence=req.confidence,
    )
    return {"status": "saved", "id": pattern_id, "fingerprint": req.fingerprint}


@app.post("/pattern-rules/suggest", response_model=PatternRuleProposalResponse)
def suggest_pattern_rule(req: PatternRuleSuggestRequest) -> PatternRuleProposalResponse:
    """Suggest a deterministic normalization regex/template for a cluster."""

    proposal = PatternRuleSuggestionAgent().propose(
        cluster=req.cluster, message=req.message
    )
    return PatternRuleProposalResponse(**proposal.__dict__)


@app.post("/pattern-rules")
def create_pattern_rule(req: PatternRuleSaveRequest) -> dict[str, int | str]:
    """Register an approved pattern normalization rule."""

    rule_id = save_pattern_normalization_rule(
        name=req.name,
        match_regex=req.match_regex,
        template=req.template,
        enabled=req.enabled,
        priority=req.priority,
    )
    return {"status": "saved", "id": rule_id}


@app.get(
    "/pattern-duplicates",
    response_model=DuplicatePatternCandidatesResponse,
)
def list_duplicate_pattern_candidates(
    status: str = "pending", limit: int = 50
) -> DuplicatePatternCandidatesResponse:
    """Return duplicate fingerprint candidates found after analysis."""

    return DuplicatePatternCandidatesResponse(
        candidates=fetch_duplicate_pattern_candidates(status=status, limit=limit)
    )


@app.post("/pattern-duplicates/{candidate_key}/approve")
def approve_duplicate_pattern_candidate(candidate_key: str) -> dict[str, object]:
    """Approve a duplicate candidate and register its suggested normalization rule."""

    candidates = fetch_duplicate_pattern_candidates(status="", limit=500)
    candidate = next(
        (
            item
            for item in candidates
            if str(item.get("candidate_key")) == candidate_key
        ),
        None,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Duplicate candidate not found")
    rule_id = save_pattern_normalization_rule(
        name=f"duplicate:{candidate_key}",
        match_regex=str(candidate["suggested_regex"]),
        template=str(candidate["suggested_template"]),
        enabled=True,
        priority=120,
    )
    updated = update_duplicate_pattern_candidate_status(candidate_key, "approved")
    merge_result = merge_duplicate_pattern_candidate(candidate_key, rule_id=rule_id)
    return {
        "status": "approved",
        "rule_id": rule_id,
        "candidate": updated,
        "merge": merge_result,
    }


@app.post("/pattern-duplicates/{candidate_key}/reject")
def reject_duplicate_pattern_candidate(candidate_key: str) -> dict[str, object]:
    """Reject a duplicate candidate so it is not proposed again."""

    updated = update_duplicate_pattern_candidate_status(candidate_key, "rejected")
    if updated is None:
        raise HTTPException(status_code=404, detail="Duplicate candidate not found")
    return {"status": "rejected", "candidate": updated}


@app.post("/approvals")
def approve_recommendation(req: ApprovalRequest) -> dict[str, str]:
    """Approve a recommendation and create a Knowledge Card for SC-007."""
    card_id = approve_result(
        req.fingerprint,
        req.cause,
        req.recommendation,
        req.action,
        req.confidence,
        req.resolution_method,
    )
    return {"result": "approved", "card_id": card_id}
