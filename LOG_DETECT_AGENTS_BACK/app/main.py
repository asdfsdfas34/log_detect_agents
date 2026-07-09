"""FastAPI entrypoint for 장애 예방 AI backend."""

import logging
from datetime import date
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.agents.knowledge_base_rag import KnowledgeBaseRAGAgent
from app.agents.pattern_rule_suggestion import PatternRuleSuggestionAgent
from app.agents.recommendation import RecommendationAgent
from app.config import settings
from app.db.chroma_store import (
    find_similar_analysis_documents_batch,
    find_similar_pattern_clusters_batch,
)
from app.db.scenario_store import (
    approve_result,
    fetch_duplicate_pattern_candidates,
    fetch_exception_registry,
    fetch_knowledge_cards,
    fetch_knowledge_cards_by_ids,
    fetch_pattern_cluster,
    merge_duplicate_pattern_candidate,
    merge_selected_fingerprints_as_known_pattern,
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
from app.patternops.registry import (
    fetch_pattern_contracts_for_agents,
    lookup_pattern_contracts,
    record_pattern_ops_action,
    sync_pattern_contracts_from_legacy_tables,
)
from app.patternops.runner import pattern_skill_runner
from app.patternops.skill_graph import (
    fetch_pattern_skill_edges,
    fetch_pattern_skills,
)
from app.state import Scope, SharedState, create_initial_state
from app.streaming import analysis_stream, sse_lines


class _SuppressMessagePrefixFilter(logging.Filter):
    """Drop a known noisy dependency message while preserving other records."""

    def __init__(self, message_prefix: str) -> None:
        super().__init__()
        self.message_prefix = message_prefix

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith(self.message_prefix)


def _add_message_prefix_filter_once(logger: logging.Logger, message_prefix: str) -> None:
    for existing_filter in logger.filters:
        if (
            isinstance(existing_filter, _SuppressMessagePrefixFilter)
            and existing_filter.message_prefix == message_prefix
        ):
            return
    logger.addFilter(_SuppressMessagePrefixFilter(message_prefix))


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
    logging.getLogger("drain3.template_miner").setLevel(logging.WARNING)
    _add_message_prefix_filter_once(
        logging.getLogger("chromadb.segment.impl.vector.local_persistent_hnsw"),
        "Delete of nonexisting embedding ID:",
    )


configure_logging()
configure_langsmith()

SIMILAR_PATTERN_LIST_THRESHOLD = 0.8

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
    include_similar_clusters: bool = Field(
        default=False,
        description="Include ChromaDB similar pattern matches in the analyze response",
    )
    include_time_windows: bool = Field(
        default=True,
        description="Update and include event time windows and system state vectors",
    )
    stream_id: str | None = Field(
        default=None, description="Optional client stream id for live progress events"
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
    service_name: str = ""
    category: str = "Manual"
    sub_category: str = "Known Pattern"
    cause: str
    recommendation: str
    confidence: str = "HIGH"


class FingerprintManualMergeRequest(BaseModel):
    """Request body for user-selected fingerprint merge and known registration."""

    service_name: str
    fingerprints: list[str] = Field(..., min_length=2)
    cause: str = Field(..., min_length=1)
    recommendation: str = Field(..., min_length=1)
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


class PatternClusterPartialRefreshRequest(BaseModel):
    """Request body for selected pattern cluster row refresh."""

    service_name: str = ""
    fingerprints: list[str] = Field(default_factory=list)
    include_similar_clusters: bool = True
    limit: int = 5


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
    analysis_date: date | None = None
    include_time_windows: bool = True


class ServiceListResponse(BaseModel):
    services: list[str]


class RecommendationHistoryResponse(BaseModel):
    recommendations: list[dict]


class KnowledgeCardListResponse(BaseModel):
    knowledge_cards: list[dict]


class ExceptionRegistryResponse(BaseModel):
    exceptions: list[dict]


class PatternOpsContractsResponse(BaseModel):
    contracts: list[dict]


class PatternOpsSkillsResponse(BaseModel):
    skills: list[dict]
    edges: list[dict]


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


def _is_same_pattern_match(
    match: dict, *, service_name: str, fingerprint: str
) -> bool:
    metadata = match.get("metadata") if isinstance(match.get("metadata"), dict) else {}
    match_fingerprint = str(metadata.get("fingerprint") or "")
    if match_fingerprint != fingerprint:
        return False
    match_service = str(metadata.get("service_name") or "")
    return not match_service or match_service == service_name


def _stored_similar_pattern_match(
    *, item: dict, service_name: str, fingerprint: str
) -> dict[str, object] | None:
    similar_fingerprint = str(item.get("similar_fingerprint") or "").strip()
    if not similar_fingerprint or similar_fingerprint == fingerprint:
        return None
    target = fetch_pattern_cluster(
        fingerprint=similar_fingerprint,
        service_name=service_name or str(item.get("service_name") or "") or None,
    )
    target_service = (
        str((target or {}).get("service_name") or "")
        or service_name
        or str(item.get("service_name") or "")
    )
    target_level = str((target or {}).get("log_level") or item.get("log_level") or "")
    target_message = str((target or {}).get("message") or "")
    target_stacktrace = str((target or {}).get("stacktrace") or "")
    score = item.get("similarity_score")
    similarity = float(score) if score is not None else 0.0
    document = (
        _pattern_cluster_context(
            service_name=target_service,
            fingerprint=similar_fingerprint,
            message=target_message,
            log_level=target_level,
            stacktrace=target_stacktrace,
        )
        if target
        else f"fingerprint={similar_fingerprint}"
    )
    return {
        "id": f"{target_service}:{similar_fingerprint}"
        if target_service
        else similar_fingerprint,
        "document": document,
        "metadata": {
            "fingerprint": similar_fingerprint,
            "service_name": target_service,
            "log_level": target_level,
            "source": str(item.get("match_source") or "stored_pattern_match"),
        },
        "distance": None,
        "similarity": similarity,
    }


def _prepend_stored_similar_match(
    *, item: dict, service_name: str, fingerprint: str, matches: list[dict]
) -> list[dict]:
    stored_match = _stored_similar_pattern_match(
        item=item,
        service_name=service_name,
        fingerprint=fingerprint,
    )
    if not stored_match:
        return matches
    stored_fingerprint = str(
        (stored_match.get("metadata") or {}).get("fingerprint") or ""
    )
    deduped = [
        match
        for match in matches
        if str((match.get("metadata") or {}).get("fingerprint") or match.get("id") or "")
        != stored_fingerprint
    ]
    return [stored_match, *deduped]


def _enrich_pattern_clusters(
    *,
    service_name: str,
    fingerprints: list[dict],
    anomalies: list[dict] | None = None,
    n_results: int = 5,
    include_similar_clusters: bool = False,
) -> list[dict]:
    enriched: list[dict] = []
    anomalies_by_pattern = {
        str(item.get("pattern")): item for item in anomalies or [] if item.get("pattern")
    }
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
        pattern_contexts.append(
            {
                "item": item,
                "query": context,
            }
        )
    similar_cluster_groups: list[list[dict]] = []
    if include_similar_clusters:
        similar_cluster_groups = find_similar_pattern_clusters_batch(
            queries=[str(item["query"]) for item in pattern_contexts],
            n_results=n_results + 1,
        )
    for index, pattern_context in enumerate(pattern_contexts):
        item = pattern_context["item"]
        similar_group = (
            similar_cluster_groups[index]
            if include_similar_clusters and index < len(similar_cluster_groups)
            else []
        )
        similar_clusters = [
            match
            for match in similar_group
            if not _is_same_pattern_match(
                match,
                service_name=service_name,
                fingerprint=str(item.get("fingerprint", "")),
            )
            and float(match.get("similarity") or 0) >= SIMILAR_PATTERN_LIST_THRESHOLD
        ][:n_results]
        fingerprint = str(item.get("fingerprint", ""))
        similar_clusters = _prepend_stored_similar_match(
            item=item,
            service_name=service_name,
            fingerprint=fingerprint,
            matches=similar_clusters,
        )[:n_results]
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
                "service_name": service_name,
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


def _dedupe_texts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        deduped.append(cleaned)
    return deduped


def _pattern_cluster_partial_refresh(
    *,
    service_name: str = "",
    fingerprints: list[str],
    include_similar_clusters: bool = True,
    n_results: int = 5,
) -> dict[str, object]:
    requested = _dedupe_texts(fingerprints)
    missing: list[str] = []
    groups_by_service: dict[str, list[dict]] = {}
    for fingerprint in requested:
        cluster = fetch_pattern_cluster(
            fingerprint=fingerprint,
            service_name=service_name or None,
        )
        if cluster is None:
            missing.append(fingerprint)
            continue
        cluster_service = service_name or str(cluster.get("service_name") or "")
        groups_by_service.setdefault(cluster_service, []).append(cluster)

    updated_clusters: list[dict] = []
    for cluster_service, cluster_rows in groups_by_service.items():
        updated_clusters.extend(
            _enrich_pattern_clusters(
                service_name=cluster_service,
                fingerprints=cluster_rows,
                n_results=max(1, n_results),
                include_similar_clusters=include_similar_clusters,
            )
        )

    return {
        "affected_fingerprints": requested,
        "updated_clusters": updated_clusters,
        "missing_fingerprints": missing,
    }


def _merge_refresh_fingerprints(result: dict[str, object]) -> list[str]:
    merge_result = result.get("merge")
    if not isinstance(merge_result, dict):
        merge_result = result
    fingerprints: list[str] = []
    canonical = merge_result.get("canonical_fingerprint")
    if canonical:
        fingerprints.append(str(canonical))
    merged = merge_result.get("merged_fingerprints")
    if isinstance(merged, list):
        fingerprints.extend(str(item) for item in merged)
    return _dedupe_texts(fingerprints)


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


def _patternops_matches_from_fingerprints(
    *, service_name: str, fingerprints: list[dict]
) -> list[dict]:
    """Build PatternOps matches from scenario fingerprint rows."""

    matches: list[dict] = []
    for item in fingerprints:
        message = str(item.get("message") or "")
        fingerprint = str(item.get("fingerprint") or "")
        log_level = str(item.get("log_level") or "")
        normalized_message = normalize_log_text(message).lower()
        for match in lookup_pattern_contracts(
            message=message,
            normalized_message=normalized_message,
            level=log_level,
            fingerprint=fingerprint,
            service_name=service_name,
        ):
            matches.append(
                {
                    **match,
                    "system": service_name,
                    "fingerprint": fingerprint,
                    "message_template": normalized_message,
                    "message": message,
                    "occurrence_count": item.get("occurrence_count", 0),
                }
            )
    return matches


def _refresh_patternops_skill_plan(state: SharedState) -> SharedState:
    return pattern_skill_runner.run_for_agent(
        state,
        agent_name="ScenarioAnalysis",
        scope="maintenance",
    )


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


def _knowledge_card_id_from_match(match: dict) -> str:
    metadata = match.get("metadata") or {}
    card_id = str(metadata.get("card_id") or "")
    if card_id:
        return card_id
    raw_id = str(match.get("id") or "")
    for prefix in ("case-card-v2:knowledge-card:", "knowledge-card:"):
        if raw_id.startswith(prefix):
            return raw_id[len(prefix) :]
    return ""


def _related_knowledge_cards_for_recommendation(
    *,
    fingerprint: str,
    service_name: str,
    selected: dict | None,
    limit: int = 5,
) -> list[dict]:
    if not selected:
        return []
    exact_cards = [
        {
            **card,
            "match_type": "exact_fingerprint",
            "similarity": 1.0,
        }
        for card in fetch_knowledge_cards(fingerprint=fingerprint, limit=limit)
    ]

    query = _pattern_cluster_context(
        service_name=service_name,
        fingerprint=fingerprint,
        message=str(selected.get("message") or ""),
        log_level=str(selected.get("log_level") or ""),
        stacktrace=str(selected.get("stacktrace") or ""),
    )
    try:
        groups = find_similar_analysis_documents_batch(
            queries=[query], n_results=max(1, limit)
        )
    except Exception:  # noqa: BLE001
        groups = []
    ranked_matches = sorted(
        [
            match
            for match in (groups[0] if groups else [])
            if float(match.get("similarity") or 0) >= SIMILAR_PATTERN_LIST_THRESHOLD
        ],
        key=lambda match: float(match.get("similarity") or 0),
        reverse=True,
    )
    similar_card_ids = [
        card_id
        for card_id in (
            _knowledge_card_id_from_match(match) for match in ranked_matches
        )
        if card_id
    ]
    exact_card_ids = {str(card.get("card_id") or "") for card in exact_cards}
    similar_similarity_by_id = {
        _knowledge_card_id_from_match(match): float(match.get("similarity") or 0)
        for match in ranked_matches
        if _knowledge_card_id_from_match(match)
    }
    similar_cards = [
        {
            **card,
            "match_type": "semantic_similarity",
            "similarity": similar_similarity_by_id.get(str(card.get("card_id")), 0.0),
        }
        for card in fetch_knowledge_cards_by_ids(
            [card_id for card_id in similar_card_ids if card_id not in exact_card_ids]
        )
    ]
    return [*exact_cards, *similar_cards][:limit]


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


@app.get("/analyze/stream")
def analyze_stream(stream_id: str) -> StreamingResponse:
    """Stream live analysis events for a matching analyze request."""

    return StreamingResponse(
        sse_lines(stream_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    with analysis_stream(req.stream_id):
        return _analyze(req)


def _analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    graph = build_graph()
    analysis_date = req.analysis_date or date.today()
    time_range = {"from": "", "to": ""}
    time_range = {
        "from": analysis_date.isoformat(),
        "to": analysis_date.isoformat(),
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
        scenario = run_detection_pipeline(
            req.service_name,
            analysis_date=analysis_date.isoformat(),
            include_time_windows=req.include_time_windows,
        )
    except TypeError:
        scenario = run_detection_pipeline(req.service_name)
    except ValueError:
        scenario = {
            "fingerprints": [],
            "anomalies": [],
            "anomaly_daily_counts": [],
            "semantic_clusters": [],
            "trajectories": [],
            "trajectory_clusters": [],
            "nearest_trajectory_patterns": [],
            "summary": {},
            "recommendation": {},
            "recommendations": [],
        }
    result["evidence"]["summary"] = scenario["summary"]
    result["evidence"]["recommendation"] = scenario["recommendation"]
    result["evidence"]["anomaly_daily_counts"] = scenario.get(
        "anomaly_daily_counts", []
    )
    result["evidence"]["duplicate_pattern_candidates"] = scenario.get(
        "duplicate_pattern_candidates", []
    )
    result["evidence"]["fingerprint_merge_groups"] = scenario.get(
        "fingerprint_merge_groups", []
    )
    result["evidence"]["event_time_windows"] = scenario.get(
        "event_time_windows", []
    )
    result["evidence"]["system_state_vectors"] = scenario.get(
        "system_state_vectors", []
    )
    result["evidence"]["semantic_clusters"] = scenario.get("semantic_clusters", [])
    result["evidence"]["trajectories"] = scenario.get("trajectories", [])
    result["evidence"]["trajectory_clusters"] = scenario.get(
        "trajectory_clusters", []
    )
    result["evidence"]["nearest_trajectory_patterns"] = scenario.get(
        "nearest_trajectory_patterns", []
    )
    if scenario["fingerprints"]:
        result["evidence"]["pattern_ops_matches"] = _patternops_matches_from_fingerprints(
            service_name=req.service_name,
            fingerprints=scenario["fingerprints"],
        )
        result["evidence"]["pattern_ops_contracts"] = [
            {
                "pattern_id": contract.pattern_id,
                "name": contract.name,
                "category": contract.category,
                "sub_category": contract.sub_category,
                "lifecycle": contract.lifecycle,
                "confidence": contract.confidence,
                "artifact": contract.artifact,
                "validator_count": len(contract.validators),
                "source": contract.source,
            }
            for contract in fetch_pattern_contracts_for_agents(limit=50)
        ]
        result["evidence"]["clusters"] = _enrich_pattern_clusters(
            service_name=req.service_name,
            fingerprints=scenario["fingerprints"],
            anomalies=scenario.get("anomalies", []),
            include_similar_clusters=req.include_similar_clusters,
        )
        result["evidence"]["pattern_clusters"] = scenario.get("pattern_clusters", [])
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
            f"Analysis date: {analysis_date.isoformat()}",
        ]
        result["evidence"]["known_pattern_matches"] = scenario.get(
            "recommendations", []
        )[:5]
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
            "pattern_ops_summary": {
                "matched_contracts": len(
                    result["evidence"].get("pattern_ops_matches", [])
                ),
                "loaded_contracts": len(
                    result["evidence"].get("pattern_ops_contracts", [])
                ),
            },
            "pattern_ops_matches": result["evidence"].get("pattern_ops_matches", []),
            "pattern_ops_contracts": result["evidence"].get(
                "pattern_ops_contracts", []
            ),
            "pattern_ops_skill_plan": result["evidence"].get(
                "pattern_ops_skill_plan", {}
            ),
            "pattern_ops_skill_executions": result["evidence"].get(
                "pattern_ops_skill_executions", []
            ),
            "pattern_ops_validator_results": result["evidence"].get(
                "pattern_ops_validator_results", []
            ),
            "fingerprint_merge_groups": scenario.get("fingerprint_merge_groups", []),
            "event_time_windows": scenario.get("event_time_windows", []),
            "system_state_vectors": scenario.get("system_state_vectors", []),
            "semantic_clusters": scenario.get("semantic_clusters", []),
            "trajectories": scenario.get("trajectories", []),
            "trajectory_clusters": scenario.get("trajectory_clusters", []),
            "nearest_trajectory_patterns": scenario.get(
                "nearest_trajectory_patterns", []
            ),
        }
    )
    result["decisions"]["skipped_agents"].append("RecommendationAgent")
    result = _refresh_patternops_skill_plan(result)
    result["final"]["evidence_bundle"].update(
        {
            "pattern_ops_skill_plan": result["evidence"].get(
                "pattern_ops_skill_plan", {}
            ),
            "pattern_ops_skill_executions": result["evidence"].get(
                "pattern_ops_skill_executions", []
            ),
            "pattern_ops_validator_results": result["evidence"].get(
                "pattern_ops_validator_results", []
            ),
        }
    )

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
    analysis_date = req.analysis_date or date.today()
    scenario = run_detection_pipeline(
        req.service_name,
        analysis_date=analysis_date.isoformat(),
        include_time_windows=req.include_time_windows,
    )
    selected = next(
        (
            item
            for item in scenario["fingerprints"]
            if item["fingerprint"] == req.fingerprint
        ),
        None,
    )
    if selected is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Fingerprint '{req.fingerprint}' was not found for "
                f"service '{req.service_name}' on {analysis_date.isoformat()}."
            ),
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
        selected_semantic_clusters = [
            cluster
            for cluster in scenario.get("semantic_clusters", [])
            if req.fingerprint in cluster.get("fingerprints", [])
        ]
        state["evidence"]["pattern_ops_matches"] = _patternops_matches_from_fingerprints(
            service_name=req.service_name,
            fingerprints=[selected],
        )
        state["evidence"]["pattern_ops_contracts"] = [
            {
                "pattern_id": contract.pattern_id,
                "name": contract.name,
                "category": contract.category,
                "sub_category": contract.sub_category,
                "lifecycle": contract.lifecycle,
                "confidence": contract.confidence,
                "artifact": contract.artifact,
                "validator_count": len(contract.validators),
                "source": contract.source,
            }
            for contract in fetch_pattern_contracts_for_agents(limit=50)
        ]
        state["evidence"]["clusters"] = _enrich_pattern_clusters(
            service_name=req.service_name,
            fingerprints=[selected],
            anomalies=scenario.get("anomalies", []),
            include_similar_clusters=True,
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
        state["evidence"]["semantic_clusters"] = selected_semantic_clusters
        state["evidence"]["trajectories"] = scenario.get("trajectories", [])
        state["evidence"]["trajectory_clusters"] = scenario.get(
            "trajectory_clusters", []
        )
        state["evidence"]["nearest_trajectory_patterns"] = scenario.get(
            "nearest_trajectory_patterns", []
        )
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
    state["rag"]["related_knowledge"] = _related_knowledge_cards_for_recommendation(
        fingerprint=req.fingerprint,
        service_name=req.service_name,
        selected=selected,
        limit=5,
    )
    state["assessment"]["risk_score"] = selected_impact["risk_score"]
    state["assessment"]["confidence"] = (
        "high" if selected_recommendation.get("confidence") == "HIGH" else "mid"
    )
    state["assessment"]["rationale"] = [
        f"Selected Fingerprint: {req.fingerprint}",
        f"Risk Level: {selected_impact['risk_level']}",
        f"Rule/knowledge recommendation hint: {selected_recommendation.get('recommendation', '-')}",
    ]
    state = _refresh_patternops_skill_plan(state)
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


@app.get("/patternops/contracts", response_model=PatternOpsContractsResponse)
def list_patternops_contracts(limit: int = 100) -> PatternOpsContractsResponse:
    """Return active PatternOps knowledge contracts."""

    sync_pattern_contracts_from_legacy_tables()
    return PatternOpsContractsResponse(
        contracts=[
            {
                "pattern_id": contract.pattern_id,
                "name": contract.name,
                "category": contract.category,
                "sub_category": contract.sub_category,
                "lifecycle": contract.lifecycle,
                "confidence": contract.confidence,
                "precondition": contract.precondition,
                "operation": contract.operation,
                "artifact": contract.artifact,
                "validators": contract.validators,
                "failure_modes": contract.failure_modes,
                "source": contract.source,
            }
            for contract in fetch_pattern_contracts_for_agents(limit=limit)
        ]
    )


@app.get("/patternops/skills", response_model=PatternOpsSkillsResponse)
def list_patternops_skills(limit: int = 100) -> PatternOpsSkillsResponse:
    """Return registered SkillOps-style skill graphs and graph-of-graphs edges."""

    return PatternOpsSkillsResponse(
        skills=[
            {
                "skill_id": skill.skill_id,
                "name": skill.name,
                "category": skill.category,
                "lifecycle": skill.lifecycle,
                "priority": skill.priority,
                "graph": skill.graph,
                "precondition": skill.precondition,
                "operation": skill.operation,
                "artifact": skill.artifact,
                "validators": skill.validators,
            }
            for skill in fetch_pattern_skills(limit=limit)
        ],
        edges=fetch_pattern_skill_edges(),
    )


@app.get("/pattern-clusters/{fingerprint}/similar")
def get_similar_pattern_clusters(
    fingerprint: str, service_name: str, limit: int = 5
) -> dict[str, object]:
    """Return similar pattern matches for one fingerprint on demand."""

    cluster = fetch_pattern_cluster(fingerprint=fingerprint, service_name=service_name)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Pattern cluster not found")
    query = _pattern_cluster_context(
        service_name=service_name,
        fingerprint=fingerprint,
        message=str(cluster.get("message") or ""),
        log_level=str(cluster.get("log_level") or ""),
        stacktrace=str(cluster.get("stacktrace") or ""),
    )
    groups = find_similar_pattern_clusters_batch(
        queries=[query], n_results=max(1, limit) + 1
    )
    matches = [
        match
        for match in (groups[0] if groups else [])
        if not _is_same_pattern_match(
            match, service_name=service_name, fingerprint=fingerprint
        )
        and float(match.get("similarity") or 0) >= SIMILAR_PATTERN_LIST_THRESHOLD
    ][:limit]
    matches = _prepend_stored_similar_match(
        item=cluster,
        service_name=service_name,
        fingerprint=fingerprint,
        matches=matches,
    )[:limit]
    return {
        "fingerprint": fingerprint,
        "service_name": service_name,
        "semantic_similarity": (
            round(float(matches[0]["similarity"]) * 100)
            if matches and matches[0].get("similarity") is not None
            else 0
        ),
        "similar_clusters": matches,
    }


@app.post("/pattern-clusters/refresh-selected")
def refresh_selected_pattern_clusters(
    req: PatternClusterPartialRefreshRequest,
) -> dict[str, object]:
    """Refresh only selected pattern cluster rows after local actions."""

    return _pattern_cluster_partial_refresh(
        service_name=req.service_name,
        fingerprints=req.fingerprints,
        include_similar_clusters=req.include_similar_clusters,
        n_results=req.limit,
    )


@app.post("/exceptions")
def create_exception(req: ExceptionRegisterRequest) -> dict[str, str]:
    """Register a fingerprint ignore rule for SC-006."""
    register_exception(req.fingerprint, req.reason)
    return {"status": "registered", "fingerprint": req.fingerprint}


@app.post("/known-patterns")
def create_known_pattern(req: KnownPatternSaveRequest) -> dict[str, object]:
    """Register a human-selected known pattern."""
    pattern_id = save_known_pattern(
        fingerprint=req.fingerprint,
        category=req.category,
        sub_category=req.sub_category,
        cause=req.cause,
        recommendation=req.recommendation,
        confidence=req.confidence,
    )
    sync_pattern_contracts_from_legacy_tables()
    record_pattern_ops_action(
        action_type="register_known_pattern",
        pattern_id=f"known-pattern:{pattern_id}",
        status="applied",
        payload=req.dict(),
        result={"known_pattern_id": pattern_id},
        reason="Human-selected known pattern registration",
    )
    return {
        "status": "saved",
        "id": pattern_id,
        "fingerprint": req.fingerprint,
        "partial_refresh": _pattern_cluster_partial_refresh(
            service_name=req.service_name,
            fingerprints=[req.fingerprint],
        ),
    }


@app.post("/fingerprints/manual-merge")
def manual_merge_fingerprints(req: FingerprintManualMergeRequest) -> dict[str, object]:
    """Merge user-selected fingerprints and register the canonical FP as known."""

    try:
        result = merge_selected_fingerprints_as_known_pattern(
            service_name=req.service_name,
            fingerprints=req.fingerprints,
            cause=req.cause,
            recommendation=req.recommendation,
            confidence=req.confidence,
        )
        sync_pattern_contracts_from_legacy_tables()
        action_id = record_pattern_ops_action(
            action_type="merge",
            pattern_id=str(result.get("canonical_fingerprint", "")),
            status="applied",
            payload=req.dict(),
            result=result,
            reason="Manual selected fingerprint merge",
        )
        return {
            **result,
            "pattern_ops_action_id": action_id,
            "partial_refresh": _pattern_cluster_partial_refresh(
                service_name=req.service_name,
                fingerprints=_merge_refresh_fingerprints(result),
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
    sync_pattern_contracts_from_legacy_tables()
    record_pattern_ops_action(
        action_type="add_adapter",
        pattern_id=f"normalization-rule:{rule_id}",
        status="applied",
        payload=req.dict(),
        result={"rule_id": rule_id},
        reason="Approved normalization rule registered as PatternOps adapter",
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
    sync_pattern_contracts_from_legacy_tables()
    action_id = record_pattern_ops_action(
        action_type="merge",
        pattern_id=str(merge_result.get("canonical_fingerprint", "")),
        status="applied",
        payload={"candidate_key": candidate_key, "candidate": candidate},
        result={"rule_id": rule_id, "merge": merge_result},
        reason="Approved duplicate pattern candidate",
    )
    return {
        "status": "approved",
        "rule_id": rule_id,
        "candidate": updated,
        "merge": merge_result,
        "pattern_ops_action_id": action_id,
        "partial_refresh": _pattern_cluster_partial_refresh(
            service_name=str(candidate.get("service_name") or ""),
            fingerprints=_merge_refresh_fingerprints(merge_result),
        ),
    }


@app.post("/pattern-duplicates/{candidate_key}/reject")
def reject_duplicate_pattern_candidate(candidate_key: str) -> dict[str, object]:
    """Reject a duplicate candidate so it is not proposed again."""

    updated = update_duplicate_pattern_candidate_status(candidate_key, "rejected")
    if updated is None:
        raise HTTPException(status_code=404, detail="Duplicate candidate not found")
    record_pattern_ops_action(
        action_type="reject",
        pattern_id=candidate_key,
        status="applied",
        payload={"candidate_key": candidate_key},
        result={"candidate": updated},
        reason="Duplicate pattern candidate rejected",
    )
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
    sync_pattern_contracts_from_legacy_tables()
    record_pattern_ops_action(
        action_type="capture_resolution",
        pattern_id=req.fingerprint,
        status="applied",
        payload=req.dict(),
        result={"card_id": card_id},
        reason="Approved recommendation captured as PatternOps case contract",
    )
    return {"result": "approved", "card_id": card_id}
