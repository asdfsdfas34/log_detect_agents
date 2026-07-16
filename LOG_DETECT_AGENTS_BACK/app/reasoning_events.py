"""High-level agent reasoning events safe for dashboard display."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

from app.state import SharedState
from app.streaming import emit_event

ReasoningKind = Literal["planning", "tool_call", "self_correction"]
ReasoningStatus = Literal["planned", "running", "completed", "failed"]

_current_state: ContextVar[SharedState | None] = ContextVar(
    "current_reasoning_state", default=None
)
_current_agent: ContextVar[str] = ContextVar("current_reasoning_agent", default="Agent")


@contextmanager
def reasoning_state(state: SharedState, *, agent_name: str = "Agent") -> Iterator[None]:
    """Bind a shared state so nested MCP calls can record high-level events."""

    state_token = _current_state.set(state)
    agent_token = _current_agent.set(agent_name)
    try:
        yield
    finally:
        _current_agent.reset(agent_token)
        _current_state.reset(state_token)


def current_reasoning_state() -> SharedState | None:
    """Return the state currently bound to an agent operation, if any."""

    return _current_state.get()


def current_reasoning_agent() -> str:
    """Return the agent name bound to the current operation."""

    return _current_agent.get()


def record_reasoning_event(
    state: SharedState,
    *,
    kind: ReasoningKind,
    agent: str,
    status: ReasoningStatus,
    title: str,
    detail: str,
    metadata: dict[str, Any] | None = None,
    mirror_trace: bool = True,
) -> dict[str, Any]:
    """Store and stream a concise event without exposing prompts or raw tool payloads.

    ``mirror_trace`` projects the event onto the structured trace stream. Callers
    that emit their own, semantically precise ``record_trace_event`` calls (for
    example the recommendation quality gate) pass ``mirror_trace=False`` to avoid
    duplicate or mislabelled trace events, while keeping the reasoning event and
    the existing summary activity stream unchanged.
    """

    events = state["evidence"].setdefault("agent_reasoning_events", [])
    event = {
        "event_id": f"{state.get('request_id', '')}:reasoning:{len(events) + 1}",
        "request_id": str(state.get("request_id", "")),
        "kind": kind,
        "agent_name": agent,
        "status": status,
        "title": title,
        "detail": detail,
        "metadata": metadata or {},
    }
    events.append(event)
    emit_event("reasoning", event)
    if not mirror_trace:
        return event
    _mirror_to_trace(
        state,
        kind=kind,
        agent=agent,
        status=status,
        title=title,
        detail=detail,
        metadata=metadata or {},
    )
    return event


def _mirror_to_trace(
    state: SharedState,
    *,
    kind: ReasoningKind,
    agent: str,
    status: ReasoningStatus,
    title: str,
    detail: str,
    metadata: dict[str, Any],
) -> None:
    """Project a reasoning event onto the richer structured trace stream.

    Kept import-local so ``reasoning_events`` never hard-depends on the trace
    layer, and so a trace failure can never break the reasoning flow.
    """

    try:
        from app.trace_events import (
            record_trace_event,
            tool_component,
            tool_kind_and_type,
            tool_layer,
        )

        trace_status = "completed" if status == "planned" and kind != "self_correction" else status
        common = {
            "attempt": _as_int(metadata.get("attempt")),
            "max_attempts": _as_int(metadata.get("max_attempts")),
            "metadata": metadata,
        }

        if kind == "tool_call":
            tool_name = str(metadata.get("tool_name") or "tool")
            trace_kind, event_type = tool_kind_and_type(tool_name, status)
            record_trace_event(
                state,
                kind=trace_kind,
                event_type=event_type,
                status=status,
                title=title,
                summary=detail,
                agent_name=agent,
                component=tool_component(tool_name),
                layer=tool_layer(tool_name),
                span_id=str(metadata.get("span_id")) if metadata.get("span_id") else None,
                parent_span_id=(
                    str(metadata.get("parent_span_id"))
                    if metadata.get("parent_span_id")
                    else None
                ),
                duration_ms=_as_int(metadata.get("duration_ms")),
                input_summary=(
                    metadata.get("input_summary")
                    if isinstance(metadata.get("input_summary"), dict)
                    else None
                ),
                output_summary=(
                    metadata.get("output_summary")
                    if isinstance(metadata.get("output_summary"), dict)
                    else None
                ),
                error=metadata.get("error") if isinstance(metadata.get("error"), dict) else None,
                **common,
            )
            return

        if kind == "self_correction":
            event_type = {
                "running": "self_correction.started",
                "completed": "self_correction.completed",
                "planned": "quality.evaluated",
                "failed": "self_correction.failed",
            }.get(status, f"self_correction.{status}")
            record_trace_event(
                state,
                kind="self_correction",
                event_type=event_type,
                status=trace_status,
                title=title,
                summary=detail,
                agent_name=agent,
                component=agent,
                layer="reasoning",
                decision_summary=(
                    str(metadata.get("feedback")) if metadata.get("feedback") else None
                ),
                **common,
            )
            return

        # planning
        next_agent = str(metadata.get("next_agent") or "")
        event_type = "plan.skipped" if status == "failed" else "plan.generated"
        record_trace_event(
            state,
            kind="planning",
            event_type=event_type,
            status=trace_status,
            title=title,
            summary=detail,
            agent_name=agent,
            component=agent,
            layer="orchestration",
            decision_summary=f"다음 실행 대상: {next_agent}" if next_agent else None,
            **common,
        )
    except Exception:  # noqa: BLE001 - mirroring must never break reasoning
        return


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def summarize_tool_result(result: Any) -> str:
    """Return a bounded structural summary of an MCP result."""

    if result is None:
        return "결과 없음"
    if isinstance(result, (list, tuple, set)):
        return f"{type(result).__name__} {len(result)}건 반환"
    if isinstance(result, dict):
        return f"object {len(result)}개 필드 반환"
    if isinstance(result, str):
        return f"text {len(result)}자 반환"
    return f"{type(result).__name__} 반환"
