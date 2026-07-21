"""API-level trace tests for POST /recommendations/fingerprint.

Heavy, stateful pre-processing (run_detection_pipeline) and Chroma retrieval are
stubbed so the tests are fast and deterministic; the real trace-recording path,
MCP client and RecommendationAgent quality gate are exercised. The OpenAI call
is stubbed at the MCP server boundary so no external service is contacted.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.test_recommendation_agent import _evaluation, _recommendation

client = TestClient(app)

FINGERPRINT = "fp-timeout-0001"
SERVICE = "payment-api"


def _scenario(*_args, **_kwargs) -> dict:
    return {
        "fingerprints": [
            {
                "fingerprint": FINGERPRINT,
                "message": "payment provider timeout",
                "log_level": "ERROR",
                "stacktrace": "",
                "occurrence_count": 42,
                "anomaly_type": "SPIKE",
            }
        ],
        "recommendations": [
            {
                "fingerprint": FINGERPRINT,
                "cause": "external provider latency",
                "recommendation": "timeout 및 retry 정책을 조정합니다",
                "confidence": "HIGH",
                "sub_category": "timeout",
            }
        ],
        "impacts": [
            {
                "fingerprint": FINGERPRINT,
                "risk_score": 82,
                "risk_level": "High",
                "detected": True,
            }
        ],
        "recommendation": {
            "fingerprint": FINGERPRINT,
            "cause": "external provider latency",
            "recommendation": "timeout 및 retry 정책을 조정합니다",
            "confidence": "HIGH",
        },
        "semantic_clusters": [],
        "anomalies": [{"pattern": FINGERPRINT, "message": "payment provider timeout"}],
        "trajectories": [],
        "trajectory_clusters": [],
        "nearest_trajectory_patterns": [],
        "summary": {
            "risk_score": 82,
            "risk_level": "High",
            "detection_status": "Detected",
        },
    }


class _FakeGenerate:
    """Stub for app.mcp.server.generate_text (never calls OpenAI)."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def __call__(self, *, messages, model=None, temperature: float = 0.2) -> str:
        self.calls += 1
        if self.responses:
            return self.responses.pop(0)
        raise AssertionError("no more fake LLM responses queued")


@pytest.fixture
def stub_pipeline(monkeypatch):
    """Stub heavy pre-processing and Chroma retrieval used by the endpoint."""

    monkeypatch.setattr("app.main.run_detection_pipeline", _scenario)
    monkeypatch.setattr("app.main._enrich_pattern_clusters", lambda **kwargs: [])
    monkeypatch.setattr(
        "app.main._patternops_matches_from_fingerprints", lambda **kwargs: []
    )
    monkeypatch.setattr(
        "app.main._related_knowledge_cards_for_recommendation",
        lambda **kwargs: [{"card_id": "KC-123", "resolution_method": "timeout 조정"}],
    )


def _post(monkeypatch, responses: list[str], stream_id: str | None = None) -> dict:
    fake = _FakeGenerate(responses)
    monkeypatch.setattr("app.mcp.server.generate_text", fake)
    payload = {"service_name": SERVICE, "fingerprint": FINGERPRINT}
    if stream_id is not None:
        payload["stream_id"] = stream_id
    res = client.post("/recommendations/fingerprint", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["result"]


def test_recommendation_response_includes_trace_events(stub_pipeline, monkeypatch) -> None:
    result = _post(monkeypatch, [_recommendation(), _evaluation(92, True)])
    events = result["evidence"]["agent_trace_events"]
    assert events, "recommendation result must carry agent_trace_events"
    assert all(event["request_id"] == result["request_id"] for event in events)


def test_recommendation_lifecycle_order(stub_pipeline, monkeypatch) -> None:
    events = _post(monkeypatch, [_recommendation(), _evaluation(92, True)])[
        "evidence"
    ]["agent_trace_events"]
    types = [event["event_type"] for event in events]

    for required in (
        "request.accepted",
        "request.validated",
        "agent.started",
        "agent.completed",
        "request.completed",
    ):
        assert required in types, f"missing {required}"

    assert types.index("request.accepted") < types.index("agent.started")
    assert types.index("agent.started") < types.index("agent.completed")
    assert types.index("agent.completed") < types.index("request.completed")

    # A skill and an LLM tool call occur between agent start and completion.
    kinds_between = {
        event["kind"]
        for event in events
        if types.index("agent.started")
        <= event["sequence"] - 1
        <= types.index("agent.completed")
    }
    assert "skill" in kinds_between
    assert "llm" in kinds_between

    agent_events = [event for event in events if event["kind"] == "agent"]
    assert len({event["span_id"] for event in agent_events}) == 1
    completed = next(e for e in agent_events if e["event_type"] == "agent.completed")
    assert completed["duration_ms"] is not None


def test_first_pass_records_quality_without_self_correction(
    stub_pipeline, monkeypatch
) -> None:
    events = _post(monkeypatch, [_recommendation(), _evaluation(92, True)])[
        "evidence"
    ]["agent_trace_events"]
    quality = [e for e in events if e["event_type"] == "quality.evaluated"]
    assert len(quality) == 1
    assert quality[0]["metadata"]["score"] == 92
    assert quality[0]["metadata"]["passed"] is True
    # No Self-Correction when the first candidate already passes.
    assert not [e for e in events if e["kind"] == "self_correction"]


def test_self_correction_recorded_after_first_failure(
    stub_pipeline, monkeypatch
) -> None:
    events = _post(
        monkeypatch,
        [
            _recommendation("timeout 원인을 검토합니다"),
            _evaluation(72, False, "구체적인 수정 대상을 추가하세요."),
            _recommendation("PaymentClient.call timeout 처리 로직을 보강합니다"),
            _evaluation(92, True),
        ],
    )["evidence"]["agent_trace_events"]

    quality_scores = [
        e["metadata"]["score"] for e in events if e["event_type"] == "quality.evaluated"
    ]
    assert quality_scores == [72, 92]
    started = [e for e in events if e["event_type"] == "self_correction.started"]
    completed = [e for e in events if e["event_type"] == "self_correction.completed"]
    assert [e["attempt"] for e in started] == [2]
    assert [e["attempt"] for e in completed] == [2]


def test_fallback_activated(stub_pipeline, monkeypatch) -> None:
    events = _post(monkeypatch, ["not-json", "not-json", "not-json"])[
        "evidence"
    ]["agent_trace_events"]
    fallback = [e for e in events if e["event_type"] == "fallback.activated"]
    assert len(fallback) == 1
    assert fallback[0]["fallback_used"] is True


def test_recommendation_without_stream_id_still_works(
    stub_pipeline, monkeypatch
) -> None:
    result = _post(monkeypatch, [_recommendation(), _evaluation(92, True)], stream_id=None)
    events = result["evidence"]["agent_trace_events"]
    assert events
    types = [event["event_type"] for event in events]
    assert "sse.connected" not in types  # no stream => no SSE lifecycle events


def test_trace_does_not_leak_prompts_args_or_secrets(stub_pipeline, monkeypatch) -> None:
    events = _post(
        monkeypatch,
        [
            _recommendation("PaymentClient.call timeout 처리 로직을 보강합니다"),
            _evaluation(92, True),
        ],
    )["evidence"]["agent_trace_events"]
    blob = json.dumps(events, ensure_ascii=False)

    # Raw LLM output text (the recommendation body) must not appear on the trace.
    assert "PaymentClient.call timeout 처리 로직을 보강합니다" not in blob
    assert "OPENAI_API_KEY" not in blob
    assert "sk-" not in blob

    for event in (e for e in events if e["kind"] == "llm"):
        if event["output_summary"] is not None:
            assert set(event["output_summary"].keys()).issubset(
                {"type", "count", "field_count", "length"}
            )
