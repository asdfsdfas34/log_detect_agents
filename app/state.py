"""Shared state schema for multi-agent orchestration."""

from typing import Literal

from typing_extensions import TypedDict


class Scope(TypedDict):
    systems: list[str]
    time_range: dict[str, str]
    filters: dict


class Evidence(TypedDict):
    normalized_logs: list[dict]
    anomalies: list[dict]
    clusters: list[dict]
    stack_traces: list[str]


class Metrics(TypedDict):
    error_rate: float | None
    latency_p95: float | None
    rps: float | None


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


class SharedState(TypedDict):
    goal: str
    scope: Scope
    evidence: Evidence
    metrics: Metrics
    assessment: Assessment
    decisions: Decisions
    final: Final


def create_initial_state(goal: str, scope: Scope) -> SharedState:
    """Build a fully-initialized shared state."""

    return {
        "goal": goal,
        "scope": scope,
        "evidence": {
            "normalized_logs": [],
            "anomalies": [],
            "clusters": [],
            "stack_traces": [],
        },
        "metrics": {"error_rate": None, "latency_p95": None, "rps": None},
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
        },
    }
