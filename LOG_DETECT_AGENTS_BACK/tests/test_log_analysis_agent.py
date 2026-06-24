import sqlite3
from pathlib import Path

from app.agents.log_analysis import LogAnalysisAgent
from app.db.scenario_store import ensure_schema
from app.state import create_initial_state


def test_log_analysis_uses_deterministic_known_pattern_matching_without_llm(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    def _raise_if_llm_called(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("LogAnalysisAgent must not call the LLM")

    monkeypatch.setattr("app.mcp.server.generate_text", _raise_if_llm_called)

    state = create_initial_state(
        goal="payment timeout investigation",
        scope={"systems": ["payment-api"], "time_range": {}, "filters": {}},
        request_id="req-log-analysis",
    )
    state["evidence"]["normalized_logs"] = [
        {
            "timestamp": "2026-06-17T10:00:00",
            "system": "payment-api",
            "level": "WARN",
            "message": "Broken pipe while writing response to client",
            "stack_trace": "BrokenPipeError: client disconnected",
        },
        {
            "timestamp": "2026-06-17T10:00:01",
            "system": "payment-api",
            "level": "ERROR",
            "message": "Payment request failed: timeout after 5000ms for user=12345",
            "stack_trace": "PaymentClient.call -> TimeoutError",
        },
        {
            "timestamp": "2026-06-17T10:00:02",
            "system": "payment-api",
            "level": "ERROR",
            "message": "Payment request failed: timeout after 3000ms for user=67890",
            "stack_trace": "PaymentClient.call -> TimeoutError",
        },
    ]

    result = LogAnalysisAgent().run(state)

    assert result["evidence"]["suppressed_logs"][0]["fingerprint"].startswith("FP-")
    assert result["evidence"]["known_pattern_matches"][0]["match_result"] == "known_suppressed"
    assert result["evidence"]["new_pattern_candidates"]
    assert len(result["evidence"]["new_pattern_candidates"]) == 1
    assert result["evidence"]["new_pattern_candidates"][0]["message_template"] == (
        "payment request failed: timeout after <duration> for user=<number>"
    )
    assert result["evidence"]["anomalies"][0]["pattern_status"] == "new_pattern_candidate"
    assert any(
        "Known Pattern Registry deterministic check" in item
        for item in result["decisions"]["assumptions"]
    )

    monkeypatch.delenv("SQLITE_PATH", raising=False)


def test_log_analysis_merges_db_known_patterns(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    message = "Payment request failed: timeout after 5000ms for user=12345"
    normalized = LogAnalysisAgent._normalize_message(message)
    fingerprint = LogAnalysisAgent._fingerprint(normalized)

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO known_patterns(
                fingerprint, category, sub_category, cause, recommendation, confidence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                "Timeout",
                "Payment Timeout",
                "payment provider latency",
                "increase provider timeout budget",
                "HIGH",
            ),
        )
        conn.commit()

    state = create_initial_state(
        goal="payment timeout investigation",
        scope={"systems": ["payment-api"], "time_range": {}, "filters": {}},
        request_id="req-db-known-pattern",
    )
    state["evidence"]["normalized_logs"] = [
        {
            "timestamp": "2026-06-17T10:00:01",
            "system": "payment-api",
            "level": "ERROR",
            "message": message,
            "stack_trace": "PaymentClient.call -> TimeoutError",
        }
    ]

    result = LogAnalysisAgent().run(state)

    assert result["evidence"]["known_pattern_matches"][0]["source"] == "db"
    assert result["evidence"]["known_pattern_matches"][0]["pattern"] == "Payment Timeout"
    assert "db_fingerprint" in result["evidence"]["known_pattern_matches"][0]["matched_by"]
    assert result["evidence"]["new_pattern_candidates"] == []

    monkeypatch.delenv("SQLITE_PATH", raising=False)
