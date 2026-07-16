"""Tests for the structured agent process trace event stream."""

import json

from fastapi.testclient import TestClient

from app.graph.nodes import _run_with_retry
from app.main import app
from app.mcp.client import MCPClient
from app.reasoning_events import reasoning_state
from app.state import create_initial_state
from app.trace_events import record_trace_event

client = TestClient(app)


def _state(request_id: str = "req-trace"):
    return create_initial_state(
        goal="trace test",
        scope={"systems": ["checkout"], "time_range": {}, "filters": {}},
        request_id=request_id,
    )


class _FakeServer:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result if result is not None else [{"message": "sensitive log"}]
        self._error = error
        self.calls: list[tuple[str, dict]] = []

    def call_tool(self, tool_name: str, arguments: dict):
        self.calls.append((tool_name, arguments))
        if self._error is not None:
            raise self._error
        return self._result


def test_record_trace_event_assigns_stable_sequence_and_ids() -> None:
    state = _state()
    first = record_trace_event(
        state,
        kind="request",
        event_type="request.accepted",
        status="running",
        title="t1",
        summary="s1",
        agent_name="FastAPI",
        component="AnalyzeAPI",
        layer="api",
    )
    second = record_trace_event(
        state,
        kind="request",
        event_type="request.completed",
        status="completed",
        title="t2",
        summary="s2",
        agent_name="FastAPI",
        component="AnalyzeAPI",
        layer="api",
    )
    assert first is not None and second is not None
    events = state["evidence"]["agent_trace_events"]
    assert [event["sequence"] for event in events] == [1, 2]
    assert first["event_id"] != second["event_id"]
    assert all(event["request_id"] == "req-trace" for event in events)
    assert all(event["timestamp"] for event in events)


def test_tool_call_trace_never_exposes_arguments_or_raw_results() -> None:
    state = _state()
    mcp = MCPClient()
    mcp._server = _FakeServer(result=[{"message": "sensitive log"}])

    with reasoning_state(state, agent_name="LogCollectorAgent"):
        mcp.call_tool("sqlite.fetch_recent_logs", {"service_name": "secret-service", "limit": 5})

    traces = state["evidence"]["agent_trace_events"]
    tool_events = [event for event in traces if event["kind"] == "tool_call"]
    assert [event["event_type"] for event in tool_events] == [
        "tool.started",
        "tool.completed",
    ]
    # Both start and end share the same span for duration pairing.
    assert tool_events[0]["span_id"] == tool_events[1]["span_id"]
    assert tool_events[1]["duration_ms"] is not None
    assert tool_events[0]["input_summary"] == {
        "field_names": ["limit", "service_name"],
        "field_count": 2,
    }
    assert tool_events[1]["output_summary"] == {"type": "list", "count": 1}
    rendered = json.dumps(traces, ensure_ascii=False)
    assert "secret-service" not in rendered
    assert "sensitive log" not in rendered
    assert "service_name" in rendered  # field name only


def test_tool_call_failure_records_safe_error() -> None:
    state = _state()
    mcp = MCPClient()
    mcp._server = _FakeServer(error=RuntimeError("db password=hunter2 leaked"))

    with reasoning_state(state, agent_name="LogCollectorAgent"):
        try:
            mcp.call_tool("sqlite.fetch_recent_logs", {"service_name": "svc"})
        except RuntimeError:
            pass

    tool_events = [
        event
        for event in state["evidence"]["agent_trace_events"]
        if event["kind"] == "tool_call"
    ]
    failed = [event for event in tool_events if event["event_type"] == "tool.failed"]
    assert len(failed) == 1
    assert failed[0]["status"] == "failed"
    assert failed[0]["error"]["type"] == "RuntimeError"
    # Raw secret from the exception message must not leak verbatim onto the stream.
    assert "hunter2" not in json.dumps(state["evidence"]["agent_trace_events"])


def test_agent_lifecycle_records_attempts_and_retry() -> None:
    state = _state()
    calls = {"n": 0}

    def always_fail(inner_state):
        calls["n"] += 1
        raise ValueError("boom")

    _run_with_retry(state, "LogCollectorAgent", always_fail)

    agent_events = [
        event
        for event in state["evidence"]["agent_trace_events"]
        if event["kind"] == "agent"
    ]
    types = [event["event_type"] for event in agent_events]
    assert types == ["agent.started", "agent.retrying", "agent.started", "agent.failed"]
    assert [event["attempt"] for event in agent_events] == [1, 1, 2, 2]
    assert agent_events[-1]["status"] == "failed"
    assert agent_events[-1]["error"]["type"] == "ValueError"


def test_self_correction_trace_records_score_and_attempt_in_order(monkeypatch) -> None:
    from tests.test_recommendation_agent import (
        FakeMCPClient,
        _evaluation,
        _recommendation,
    )
    from tests.test_recommendation_agent import (
        _state as recommendation_state,
    )

    fake = FakeMCPClient(
        [
            _recommendation("timeout 원인을 검토합니다"),
            _evaluation(72, False, "구체적인 수정 대상을 추가하세요."),
            _recommendation("PaymentClient.call timeout 처리 로직을 보강합니다"),
            _evaluation(84, True),
        ]
    )
    monkeypatch.setattr("app.agents.recommendation.get_mcp_client", lambda: fake)

    from app.agents.recommendation import RecommendationAgent

    result = RecommendationAgent().run(recommendation_state())

    events = result["evidence"]["agent_trace_events"]
    # Every evaluation is a quality.evaluated event, in evaluation order.
    quality_scores = [
        event["metadata"]["score"]
        for event in events
        if event["event_type"] == "quality.evaluated"
    ]
    assert quality_scores == [72, 84]

    # Self-Correction only appears for the regeneration (attempt 2), not the
    # first evaluation.
    started = [event for event in events if event["event_type"] == "self_correction.started"]
    completed = [event for event in events if event["event_type"] == "self_correction.completed"]
    assert [event["attempt"] for event in started] == [2]
    assert [event["attempt"] for event in completed] == [2]
    assert completed[-1]["metadata"]["score"] == 84


def test_trace_recording_failure_does_not_break_flow(monkeypatch) -> None:
    def broken_emit(*args, **kwargs):
        raise RuntimeError("stream down")

    monkeypatch.setattr("app.trace_events.emit_event", broken_emit)
    state = _state()
    # Should swallow the error and return None instead of raising.
    assert (
        record_trace_event(
            state,
            kind="request",
            event_type="request.accepted",
            status="running",
            title="t",
            summary="s",
            agent_name="FastAPI",
            component="AnalyzeAPI",
            layer="api",
        )
        is None
    )


def test_request_isolation_keeps_events_separate() -> None:
    state_a = _state("req-a")
    state_b = _state("req-b")
    for _ in range(3):
        record_trace_event(
            state_a,
            kind="request",
            event_type="request.accepted",
            status="running",
            title="a",
            summary="a",
            agent_name="FastAPI",
            component="AnalyzeAPI",
            layer="api",
        )
    record_trace_event(
        state_b,
        kind="request",
        event_type="request.accepted",
        status="running",
        title="b",
        summary="b",
        agent_name="FastAPI",
        component="AnalyzeAPI",
        layer="api",
    )
    assert len(state_a["evidence"]["agent_trace_events"]) == 3
    assert len(state_b["evidence"]["agent_trace_events"]) == 1
    assert all(
        event["request_id"] == "req-a"
        for event in state_a["evidence"]["agent_trace_events"]
    )


def test_analyze_emits_trace_across_process_layers() -> None:
    res = client.post(
        "/analyze",
        json={
            "service_name": "billing-api",
            "goal": "trace coverage",
            "save_to_chromadb": False,
            "scope": {
                "systems": ["billing-api"],
                "time_range": {"from": "2026-01-01T00:00:00", "to": "2026-01-01T01:00:00"},
                "filters": {},
            },
        },
    )
    assert res.status_code == 200
    events = res.json()["result"]["evidence"]["agent_trace_events"]
    assert events, "expected trace events on the analyze result"

    kinds = {event["kind"] for event in events}
    event_types = {event["event_type"] for event in events}
    # Request lifecycle plus FastAPI-service-flow (KnowledgeBaseRAGAgent) are covered.
    assert "request.accepted" in event_types
    assert "request.completed" in event_types
    assert {"request", "routing", "skill"}.issubset(kinds)
    assert any(
        event["agent_name"] == "KnowledgeBaseRAGAgent" for event in events
    )

    # Sequences are monotonic and unique within the request.
    sequences = [event["sequence"] for event in events]
    assert sequences == sorted(sequences)
    assert len(set(event["event_id"] for event in events)) == len(events)
