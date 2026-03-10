"""Shared state schema for multi-agent orchestration."""

from typing import Literal

from typing_extensions import TypedDict


class Scope(TypedDict):
    systems: list[str]
    time_range: dict[str, str]
    filters: dict


class Evidence(TypedDict):
    normalized_logs: list[dict]
    suppressed_logs: list[dict]
    known_pattern_matches: list[dict]
    anomalies: list[dict]
    clusters: list[dict]
    stack_traces: list[str]
    incident_candidates: list[dict]
    source_code_evidence: list[dict]


class Metrics(TypedDict):
    error_rate: float | None
    latency_p95: float | None
    rps: float | None
    anomaly_score: float | None


class Assessment(TypedDict):
    risk_score: int | None
    confidence: Literal["low", "mid", "high"]
    rationale: list[str]


class Decisions(TypedDict):
    agents_run: list[str]
    skipped_agents: list[str]
    assumptions: list[str]
    failures: list[dict]
    timeouts: list[str]


class Final(TypedDict):
    executive_summary: str | None
    recommended_actions: list[dict] | None
    verification_steps: list[str] | None
    additional_data_needed: list[str] | None
    generated_answer: str | None
    evidence_bundle: dict | None


class Orchestration(TypedDict):
    next_agent: str | None
    pending_agents: list[str]
    completed_agents: list[str]


class Preferences(TypedDict):
    save_to_chromadb: bool


class SharedState(TypedDict):
    goal: str
    request_id: str
    scope: Scope
    evidence: Evidence
    metrics: Metrics
    assessment: Assessment
    decisions: Decisions
    final: Final
    orchestration: Orchestration
    preferences: Preferences
    rag: dict


def create_initial_state(goal: str, scope: Scope, request_id: str, save_to_chromadb: bool = False) -> SharedState:
    """Build a fully-initialized shared state."""

    return {
        "goal": goal,
        "request_id": request_id,
        "scope": scope,
        "evidence": {
            "normalized_logs": [],
            "suppressed_logs": [],
            "known_pattern_matches": [],
            "anomalies": [],
            "clusters": [],
            "stack_traces": [],
            "incident_candidates": [],
            "source_code_evidence": [],
        },
        "metrics": {"error_rate": None, "latency_p95": None, "rps": None, "anomaly_score": None},
        "assessment": {"risk_score": None, "confidence": "low", "rationale": []},
        "decisions": {
            "agents_run": [],
            "skipped_agents": [],
            "assumptions": [],
            "failures": [],
            "timeouts": [],
        },
        "final": {
            "executive_summary": None,
            "recommended_actions": None,
            "verification_steps": None,
            "additional_data_needed": None,
            "generated_answer": None,
            "evidence_bundle": None,
        },
        "orchestration": {
            "next_agent": None,
            "pending_agents": [],
            "completed_agents": [],
        },
        "preferences": {"save_to_chromadb": save_to_chromadb},
        "rag": {"related_knowledge": [], "saved_to_chromadb": False},
    }
