import sqlite3
from pathlib import Path

from app.agents.log_analysis import LogAnalysisAgent
from app.db.scenario_store import ensure_schema
from app.patternops.registry import (
    fetch_pattern_contracts_for_agents,
    lookup_pattern_contracts,
    sync_pattern_contracts_from_legacy_tables,
)
from app.patternops.runner import pattern_skill_runner
from app.patternops.skill_graph import (
    fetch_pattern_skill_edges,
    fetch_pattern_skills,
    plan_skill_graphs,
)
from app.state import create_initial_state


def test_patternops_syncs_legacy_known_patterns(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO known_patterns(
                fingerprint, category, sub_category, cause, recommendation, confidence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "FP-PAYMENT",
                "Timeout",
                "Payment Timeout",
                "payment provider latency",
                "check provider latency and retry budget",
                "HIGH",
            ),
        )
        conn.commit()

    assert sync_pattern_contracts_from_legacy_tables() >= 1
    contracts = fetch_pattern_contracts_for_agents()

    contract = next(item for item in contracts if item.pattern_id == "KP-000001")
    assert contract.artifact["fingerprint"] == "FP-PAYMENT"
    assert contract.operation["analysis_type"] == "known_pattern"
    assert contract.validators[0]["validator_type"] == "fingerprint_or_similarity"

    matches = lookup_pattern_contracts(
        message="Payment request failed",
        normalized_message="payment request failed",
        level="ERROR",
        fingerprint="FP-PAYMENT",
        service_name="payment-api",
    )
    assert matches[0]["pattern_id"] == "KP-000001"
    assert "fingerprint" in matches[0]["matched_by"]


def test_log_analysis_populates_patternops_evidence(
    tmp_path: Path, monkeypatch
) -> None:
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
                "check provider latency and retry budget",
                "HIGH",
            ),
        )
        conn.commit()

    state = create_initial_state(
        goal="payment timeout investigation",
        scope={"systems": ["payment-api"], "time_range": {}, "filters": {}},
        request_id="req-patternops",
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

    assert result["evidence"]["pattern_ops_matches"]
    assert result["evidence"]["pattern_ops_matches"][0]["pattern_id"] == "KP-000001"
    assert result["evidence"]["pattern_ops_contracts"]
    assert any(
        "pattern_ops_matches=1" in item for item in result["decisions"]["assumptions"]
    )


def test_skillops_registry_excludes_impact_evaluation_and_plans_skills(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)

    skills = fetch_pattern_skills()
    skill_ids = {skill.skill_id for skill in skills}
    assert "impact_evaluation" not in skill_ids
    assert "known_pattern_match" in skill_ids
    assert "recommendation_generation" in skill_ids

    edges = fetch_pattern_skill_edges()
    assert all(edge["from_skill_id"] != "impact_evaluation" for edge in edges)
    assert all(edge["to_skill_id"] != "impact_evaluation" for edge in edges)
    assert any(
        edge["from_skill_id"] == "anomaly_detection"
        and edge["to_skill_id"] == "recommendation_generation"
        for edge in edges
    )

    state = create_initial_state(
        goal="payment timeout investigation",
        scope={"systems": ["payment-api"], "time_range": {}, "filters": {}},
        request_id="req-skillops",
    )
    state["evidence"]["normalized_logs"] = [
        {
            "system": "payment-api",
            "level": "ERROR",
            "message": "Payment request failed",
        }
    ]
    state["evidence"]["anomalies"] = [
        {"fingerprint": "FP-1", "severity": "high", "pattern": "timeout"}
    ]
    plan = plan_skill_graphs(state)
    selected_ids = {
        str(item["skill_id"]) for item in plan.get("selected_skills", [])
    }

    assert "impact_evaluation" not in selected_ids
    assert "log_normalization" in selected_ids
    assert "known_pattern_match" in selected_ids
    assert "anomaly_detection" in selected_ids
    assert "recommendation_generation" in selected_ids


def test_scoped_skill_runner_records_agent_executed_skills(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)

    state = create_initial_state(
        goal="payment timeout investigation",
        scope={"systems": ["payment-api"], "time_range": {}, "filters": {}},
        request_id="req-scoped-runner",
    )
    state["evidence"]["normalized_logs"] = [
        {
            "system": "payment-api",
            "level": "ERROR",
            "message": "Payment request failed",
        }
    ]

    def _mark_known_pattern_match(input_state):
        input_state["evidence"]["known_pattern_matches"] = [{"matched": True}]
        return input_state

    result = pattern_skill_runner.run_for_agent(
        state,
        agent_name="LogAnalysisAgent",
        scope="log_analysis",
        operations={"known_pattern_match": _mark_known_pattern_match},
    )
    scoped_plan = result["evidence"]["pattern_ops_skill_plan"]["scoped_plans"][
        "log_analysis"
    ]
    selected_ids = {
        str(item["skill_id"]) for item in scoped_plan.get("selected_skills", [])
    }

    assert "impact_evaluation" not in selected_ids
    assert "log_normalization" in selected_ids
    assert "pattern_fingerprint" in selected_ids
    assert result["evidence"]["pattern_ops_skill_executions"]
    statuses = {
        item["skill_id"]: item["status"]
        for item in result["evidence"]["pattern_ops_skill_executions"]
    }
    assert statuses["known_pattern_match"] == "success"
    assert statuses["log_normalization"] == "selected"
    assert all(
        item["agent_name"] == "LogAnalysisAgent"
        and item["scope"] == "log_analysis"
        for item in result["evidence"]["pattern_ops_skill_executions"]
    )
