import sqlite3
from pathlib import Path

from app.db.scenario_store import (
    approve_result,
    ensure_schema,
    fetch_exception_registry,
    fetch_knowledge_cards,
    fingerprint_id,
    normalize_log_text,
    register_exception,
    run_detection_pipeline,
)


def test_fingerprint_normalizes_json_payload_values() -> None:
    first = (
        '.DevOpsController - IssueUpdate Success  = '
        '{"WorkID":"b3a40081-8902-4483-b52c-99da52aae493",'
        '"DevID":"09ae79d3-1def-436a-bbee-4a3854da6cbb",'
        '"DevOpsStatus":"DO000004"}'
    )
    second = (
        'DevOpsController - IssueUpdate Success  = '
        '{"WorkID":"c02f6606-db0e-4964-9267-02e65d9324db",'
        '"DevID":"5e57ac6d-9c7d-4710-a7bd-444d6b16335f",'
        '"DevOpsStatus":"DO000001"}'
    )

    assert normalize_log_text(first) == normalize_log_text(second)
    assert fingerprint_id("devops-service", "INFO", first, "") == fingerprint_id(
        "devops-service", "INFO", second, ""
    )


def test_fingerprint_normalizes_plain_text_request_values() -> None:
    first = (
        "DevOpsController - IssueUpdate Success Request "
        "WorkID : b3a40081-8902-4483-b52c-99da52aae493, "
        "DevID : 09ae79d3-1def-436a-bbee-4a3854da6cbb, "
        "DevOpsStatus : DO000004"
    )
    second = (
        "DevOpsController - IssueUpdate Success Request "
        "WorkID : c02f6606-db0e-4964-9267-02e65d9324db, "
        "DevID : 5e57ac6d-9c7d-4710-a7bd-444d6b16335f, "
        "DevOpsStatus : DO000001"
    )
    third = (
        "DevOpsController - IssueUpdate Success Request "
        "WorkID c02f6606-db0e-4964-9267-02e65d9324db "
        "DevID 5e57ac6d-9c7d-4710-a7bd-444d6b16335f "
        "DevOpsStatus DO000001"
    )

    assert normalize_log_text(first) == normalize_log_text(second)
    assert fingerprint_id("devops-service", "INFO", first, "") == fingerprint_id(
        "devops-service", "INFO", second, ""
    )
    assert fingerprint_id("devops-service", "INFO", second, "") == fingerprint_id(
        "devops-service", "INFO", third, ""
    )


def test_fingerprint_normalizes_korean_user_suffix_numbers() -> None:
    first = (
        "테스트3님 권한이 없습니다. "
        "WorkID=552f54af-69e5-4f23-8402-6e9252bdad95"
    )
    second = (
        "테스트7님 권한이 없습니다. "
        "WorkID=ece6d12a-ad85-459c-98e2-27760fc13c0d"
    )

    assert normalize_log_text(first) == normalize_log_text(second)
    assert fingerprint_id("auth-service", "WARN", first, "") == fingerprint_id(
        "auth-service", "WARN", second, ""
    )


def test_detection_pipeline_groups_similar_log_messages(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE service_logs (
                service_name TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                stack_trace TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """)
        cur.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "devops-service",
                    "INFO",
                    'DevOpsController - IssueUpdate Success = {"WorkID":"b3a40081-8902-4483-b52c-99da52aae493","DevID":"09ae79d3-1def-436a-bbee-4a3854da6cbb","DevOpsStatus":"DO000004"}',
                    "",
                    "2026-06-16T10:00:00",
                ),
                (
                    "devops-service",
                    "INFO",
                    'DevOpsController - IssueUpdate Success = {"WorkID":"c02f6606-db0e-4964-9267-02e65d9324db","DevID":"5e57ac6d-9c7d-4710-a7bd-444d6b16335f","DevOpsStatus":"DO000001"}',
                    "",
                    "2026-06-16T10:01:00",
                ),
            ],
        )
        conn.commit()

    result = run_detection_pipeline()

    assert result["summary"]["total_logs"] == 2
    assert result["summary"]["total_fingerprints"] == 1
    assert result["fingerprints"][0]["occurrence_count"] == 2


def test_detection_pipeline_hides_exception_fingerprints_from_clusters(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    ignored_message = (
        "테스트3님 권한이 없습니다. "
        "WorkID=552f54af-69e5-4f23-8402-6e9252bdad95"
    )

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE service_logs (
                service_name TEXT NOT NULL,
                level TEXT NOT NULL,
                message TEXT NOT NULL,
                stack_trace TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
            """)
        cur.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "auth-service",
                    "WARN",
                    ignored_message,
                    "",
                    "2026-06-16T10:00:00",
                ),
                (
                    "auth-service",
                    "WARN",
                    (
                        "테스트7님 권한이 없습니다. "
                        "WorkID=ece6d12a-ad85-459c-98e2-27760fc13c0d"
                    ),
                    "",
                    "2026-06-16T10:01:00",
                ),
                (
                    "auth-service",
                    "ERROR",
                    "Login failed for client app",
                    "",
                    "2026-06-16T10:02:00",
                ),
            ],
        )
        conn.commit()

    register_exception(
        fingerprint_id("auth-service", "WARN", ignored_message, ""),
        "approved ignore",
    )

    result = run_detection_pipeline()

    assert result["summary"]["total_logs"] == 3
    assert result["summary"]["total_fingerprints"] == 1
    assert len(result["fingerprints"]) == 1
    assert result["fingerprints"][0]["message"] == "Login failed for client app"


def test_detection_pipeline_hides_clusters_similar_to_registered_exception(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO fingerprints(
                fingerprint,
                occurrence_count,
                log_level,
                message,
                stacktrace,
                service_name,
                first_seen,
                last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "FP-OLD",
                1,
                "WARN",
                "테스트3님 권한이 없습니다. WorkID=552f54af-69e5-4f23-8402-6e9252bdad95",
                "",
                "auth-service",
                "2026-06-16T09:59:00",
                "2026-06-16T09:59:00",
            ),
        )
        cur.execute(
            "INSERT INTO exception_registry(fingerprint, reason) VALUES (?, ?)",
            ("FP-OLD", "previously registered"),
        )
        cur.execute(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "auth-service",
                "WARN",
                "테스트7님 권한이 없습니다. WorkID=ece6d12a-ad85-459c-98e2-27760fc13c0d",
                "",
                "2026-06-16T10:01:00",
            ),
        )
        conn.commit()

    result = run_detection_pipeline()

    assert result["summary"]["total_logs"] == 1
    assert result["summary"]["total_fingerprints"] == 0
    assert result["fingerprints"] == []


def test_registered_items_include_message_and_level(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    message = "테스트3님 권한이 없습니다. WorkID=552f54af-69e5-4f23-8402-6e9252bdad95"

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("auth-service", "WARN", message, "", "2026-06-16T10:00:00"),
        )
        conn.commit()

    result = run_detection_pipeline()
    fingerprint = result["fingerprints"][0]["fingerprint"]
    register_exception(fingerprint, "approved ignore")
    approve_result(fingerprint, "permission denied", "check role mapping", "approved", "HIGH")

    exceptions = fetch_exception_registry(fingerprint=fingerprint)
    cards = fetch_knowledge_cards(fingerprint=fingerprint)

    assert exceptions[0]["message"] == message
    assert exceptions[0]["log_level"] == "WARN"
    assert cards[0]["message"] == message
    assert cards[0]["log_level"] == "WARN"
