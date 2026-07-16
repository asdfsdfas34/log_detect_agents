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
) -> dict[str, Any]:
    """Store and stream a concise event without exposing prompts or raw tool payloads."""

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
    return event


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
