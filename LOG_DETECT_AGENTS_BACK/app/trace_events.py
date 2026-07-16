"""Structured, redaction-safe process trace events for the observability screen.

This module extends the high-level ``reasoning`` stream into a general
``AgentTraceEvent`` contract that captures planning, routing, agent lifecycle,
skill execution, tool observations, validation, self-correction, retrieval and
persistence across both the LangGraph pipeline and the FastAPI service flow.

Only structural summaries and masked references are ever recorded. Raw prompts,
raw tool arguments/results, secrets, personal data and full stack traces are
never placed on the event stream.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.state import SharedState
from app.streaming import emit_event

TraceKind = Literal[
    "request",
    "planning",
    "routing",
    "agent",
    "skill",
    "tool_call",
    "observation",
    "validation",
    "retrieval",
    "persistence",
    "llm",
    "self_correction",
    "quality",
    "fallback",
    "sse",
]

TraceStatus = Literal["planned", "running", "completed", "failed", "skipped"]

TraceLayer = Literal[
    "client",
    "api",
    "orchestration",
    "agent",
    "skill",
    "reasoning",
    "data_access",
    "retrieval",
    "llm",
    "persistence",
]

# Maximum length for any free-text summary placed on the stream.
_MAX_SUMMARY_CHARS = 400
_TRACE_EVENTS_KEY = "agent_trace_events"


def _trace_events(state: SharedState) -> list[dict[str, Any]]:
    evidence = state.setdefault("evidence", {})  # type: ignore[arg-type]
    events = evidence.get(_TRACE_EVENTS_KEY)
    if not isinstance(events, list):
        events = []
        evidence[_TRACE_EVENTS_KEY] = events
    return events


def next_trace_span_index(state: SharedState, prefix: str) -> int:
    """Return a stable per-request span index for a start/end event pair.

    Callers compute the index once at the start of an operation and reuse the
    resulting ``span_id`` for the matching completion event so the frontend can
    pair them and compute a duration.
    """

    events = _trace_events(state)
    count = sum(1 for event in events if str(event.get("span_id", "")).startswith(prefix))
    return count + 1


def record_trace_event(
    state: SharedState,
    *,
    kind: TraceKind,
    event_type: str,
    status: TraceStatus,
    title: str,
    summary: str,
    agent_name: str,
    component: str,
    layer: TraceLayer,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    duration_ms: int | None = None,
    attempt: int | None = None,
    max_attempts: int | None = None,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    decision_summary: str | None = None,
    evidence_refs: list[str] | None = None,
    error: dict[str, Any] | None = None,
    fallback_used: bool = False,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Store and stream one structured trace event.

    Trace recording is best-effort: any failure here is swallowed so it can
    never break the underlying analysis flow (graceful degradation).
    """

    try:
        request_id = str(state.get("request_id", ""))
        events = _trace_events(state)
        sequence = len(events) + 1
        event = {
            "event_id": f"{request_id}:trace:{sequence}",
            "request_id": request_id,
            "trace_id": request_id,
            "span_id": span_id or f"{request_id}:span:{sequence}",
            "parent_span_id": parent_span_id,
            "sequence": sequence,
            "timestamp": datetime.now(UTC).isoformat(),
            "duration_ms": duration_ms,
            "layer": layer,
            "component": component,
            "agent_name": agent_name,
            "kind": kind,
            "event_type": event_type,
            "status": status,
            "title": _safe_text(title),
            "summary": _safe_text(summary),
            "input_summary": input_summary,
            "output_summary": output_summary,
            "decision_summary": _safe_text(decision_summary) if decision_summary else None,
            "evidence_refs": [str(ref) for ref in (evidence_refs or [])][:20],
            "attempt": attempt,
            "max_attempts": max_attempts,
            "error": error,
            "fallback_used": bool(fallback_used),
            "metadata": _safe_metadata(metadata),
        }
        events.append(event)
        emit_event("trace", event)
        return event
    except Exception:  # noqa: BLE001 - trace failures must never break analysis
        return None


def summarize_tool_result(result: Any) -> dict[str, Any]:
    """Return a bounded structural summary of an MCP result (never raw values)."""

    if result is None:
        return {"type": "none", "count": 0}
    if isinstance(result, (list, tuple, set)):
        return {"type": "list", "count": len(result)}
    if isinstance(result, dict):
        return {"type": "object", "field_count": len(result)}
    if isinstance(result, str):
        return {"type": "text", "length": len(result)}
    if isinstance(result, bool):
        return {"type": "bool"}
    if isinstance(result, (int, float)):
        return {"type": "number"}
    return {"type": type(result).__name__}


def tool_input_summary(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """Return only the field names of tool arguments, never their values."""

    fields = sorted(str(key) for key in (arguments or {}))
    return {"field_names": fields, "field_count": len(fields)}


def redact_error(exc: BaseException) -> dict[str, Any]:
    """Return the exception type only.

    The raw exception message is intentionally dropped: it frequently embeds
    secrets, connection strings, tokens or personal data. Only the exception
    type and a fixed, safe summary are ever placed on the stream (no message,
    no stack trace).
    """

    return {
        "type": type(exc).__name__,
        "summary": f"{type(exc).__name__} 예외가 발생했습니다.",
    }


def tool_layer(tool_name: str) -> TraceLayer:
    if tool_name.startswith("sqlite."):
        return "data_access"
    if tool_name.startswith("chromadb."):
        return "retrieval"
    if tool_name.startswith("openai."):
        return "llm"
    return "data_access"


def tool_component(tool_name: str) -> str:
    if tool_name.startswith("sqlite."):
        return "SQLiteStore"
    if tool_name.startswith("chromadb."):
        return "ChromaStore"
    if tool_name.startswith("openai."):
        return "OpenAIClient"
    return "MCPClient"


def tool_kind_and_type(tool_name: str, status: TraceStatus) -> tuple[TraceKind, str]:
    """Map an MCP tool call to a trace kind and event_type by dependency."""

    phase = {"running": "started", "completed": "completed", "failed": "failed"}.get(
        status, status
    )
    if tool_name.startswith("chromadb.save") or tool_name.startswith("chromadb.upsert"):
        return "persistence", f"persistence.{phase}"
    if tool_name.startswith("chromadb."):
        return "retrieval", f"retrieval.{phase}"
    if tool_name.startswith("openai."):
        return "llm", f"llm.generation_{phase}"
    return "tool_call", f"tool.{phase}"


def _safe_text(value: str | None, *, limit: int = _MAX_SUMMARY_CHARS) -> str:
    text = str(value or "").strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _safe_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Bound metadata to safe primitives, keys and short strings only."""

    if not isinstance(metadata, dict):
        return {}
    safe: dict[str, Any] = {}
    for key, value in metadata.items():
        safe_key = str(key)
        if isinstance(value, bool) or value is None:
            safe[safe_key] = value
        elif isinstance(value, (int, float)):
            safe[safe_key] = value
        elif isinstance(value, str):
            safe[safe_key] = _safe_text(value, limit=160)
        elif isinstance(value, (list, tuple)):
            safe[safe_key] = [
                _safe_text(str(item), limit=80) for item in list(value)[:20]
            ]
        else:
            safe[safe_key] = _safe_text(str(value), limit=80)
    return safe
