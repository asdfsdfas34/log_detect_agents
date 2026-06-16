import sqlite3
from pathlib import Path

from app.db.sqlite_store import (
    fetch_latest_log_analyses,
    fetch_recent_log_entries,
    fetch_recent_logs,
    save_impact_evaluation,
    save_recommendation_result,
    fetch_latest_recommendation_results,
    save_log_analysis,
)


def test_fetch_recent_logs_from_sqlite(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE service_logs (
                service_name TEXT,
                level TEXT,
                message TEXT,
                created_at TEXT,
                stack_trace TEXT
            )
            """)
        cur.execute(
            """
            INSERT INTO service_logs(service_name, level, message, created_at, stack_trace)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "checkout-api",
                "ERROR",
                "ERROR timeout",
                "2026-02-18T09:40:01",
                "trace-1",
            ),
        )
        cur.execute(
            """
            INSERT INTO service_logs(service_name, level, message, created_at, stack_trace)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("checkout-api", "WARN", "WARN retry", "2026-02-18T09:40:03", ""),
        )
        conn.commit()

    logs = fetch_recent_logs(service_name="checkout-api", limit=10)
    assert logs == ["WARN retry", "ERROR timeout"]

    entries = fetch_recent_log_entries(service_names=["checkout-api"], limit=10)
    assert entries[0]["level"] == "WARN"
    assert entries[1]["stack_trace"] == "trace-1"

    save_log_analysis(
        goal="timeout investigation",
        service_name="checkout-api",
        analysis="critical error",
    )
    analyses = fetch_latest_log_analyses(service_names=["checkout-api"], limit=5)
    assert analyses
    assert analyses[0]["analysis"] == "critical error"

    save_impact_evaluation(
        service_name="checkout-api",
        risk_score=88,
        confidence="high",
        rationale="high_severity=3",
    )

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT risk_score, confidence FROM impact_evaluations ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()

    assert row == (88, "high")

    saved_id = save_recommendation_result(
        request_id="req-1",
        service_name="checkout-api",
        goal="timeout investigation",
        executive_summary="DB timeout",
        recommendation="커넥션 풀을 점검하세요",
        recommended_actions=[
            {"priority": "P1", "action": "pool check", "owner": "backend"}
        ],
        verification_steps=["retry request"],
        evidence_bundle={"fingerprint": "FP-123"},
        risk_score=88,
        confidence="high",
    )
    assert saved_id is not None

    recommendations = fetch_latest_recommendation_results(
        service_names=["checkout-api"], limit=5
    )
    assert recommendations[0]["id"] == saved_id
    assert recommendations[0]["recommendation"] == "커넥션 풀을 점검하세요"
    assert recommendations[0]["recommended_actions"][0]["owner"] == "backend"
    assert recommendations[0]["evidence_bundle"] == {"fingerprint": "FP-123"}

    monkeypatch.delenv("SQLITE_PATH", raising=False)
    monkeypatch.delenv("POSTGRESQL_URL", raising=False)
