"""Tests for redaction-safe backend console trace logging."""

import logging

from app.state import create_initial_state
from app.trace_events import record_trace_event


def test_trace_event_is_logged_with_high_signal_fields(caplog) -> None:
    state = create_initial_state(
        goal="console trace test",
        scope={"systems": ["checkout"], "time_range": {}, "filters": {}},
        request_id="req-console",
    )
    caplog.set_level(logging.INFO, logger="app.trace_events")

    record_trace_event(
        state,
        kind="quality",
        event_type="quality.evaluated",
        status="completed",
        title="품질 평가: 72/100 (보완 필요)",
        summary="secret raw recommendation must not reach the console",
        agent_name="RecommendationAgent",
        component="RecommendationAgent",
        layer="reasoning",
        attempt=1,
        max_attempts=3,
        metadata={
            "score": 72,
            "threshold": 90,
            "passed": False,
            "hard_fail_count": 1,
            "unsafe_extra": "secret metadata",
        },
    )

    message = next(record.message for record in caplog.records if "AGENT_TRACE" in record.message)
    assert '"event_type":"quality.evaluated"' in message
    assert '"attempt":1' in message
    assert '"max_attempts":3' in message
    assert '"score":72' in message
    assert '"threshold":90' in message
    assert '"passed":false' in message
    assert '"hard_fail_count":1' in message
    assert "secret raw recommendation" not in message
    assert "secret metadata" not in message


def test_trace_console_logging_respects_log_level(caplog) -> None:
    state = create_initial_state(
        goal="console trace level test",
        scope={"systems": ["checkout"], "time_range": {}, "filters": {}},
        request_id="req-console-level",
    )
    caplog.set_level(logging.WARNING, logger="app.trace_events")

    record_trace_event(
        state,
        kind="planning",
        event_type="plan.generated",
        status="completed",
        title="Planning 완료",
        summary="계획을 생성했습니다.",
        agent_name="OrchestratorAgent",
        component="OrchestratorAgent",
        layer="orchestration",
        metadata={"next_agent": "LogCollectorAgent"},
    )

    assert not [record for record in caplog.records if "AGENT_TRACE" in record.message]
