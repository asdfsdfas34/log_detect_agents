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
        ".DevOpsController - IssueUpdate Success  = "
        '{"WorkID":"b3a40081-8902-4483-b52c-99da52aae493",'
        '"DevID":"09ae79d3-1def-436a-bbee-4a3854da6cbb",'
        '"DevOpsStatus":"DO000004"}'
    )
    second = (
        "DevOpsController - IssueUpdate Success  = "
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
    first = "테스트3님 권한이 없습니다. " "WorkID=552f54af-69e5-4f23-8402-6e9252bdad95"
    second = "테스트7님 권한이 없습니다. " "WorkID=ece6d12a-ad85-459c-98e2-27760fc13c0d"

    assert normalize_log_text(first) == normalize_log_text(second)
    assert fingerprint_id("auth-service", "WARN", first, "") == fingerprint_id(
        "auth-service", "WARN", second, ""
    )


def test_fingerprint_preserves_domain_names_while_normalizing_runtime_values() -> None:
    first = (
        "ServerScriptWorkerStat_x000D_"
        "Worker #0 (pid=56989 port=63894)_x000D_"
        "StartTime=2026-05-31 오전 4:15:02_x000D_"
        "PrivateMemorySize=63.98 MB_x000D_"
        "TimeAvg=0.05(1208), TimeMin=0, TimeMax=6"
    )
    second = (
        "ServerScriptWorkerStat_x000D_"
        "Worker #0 (pid=69962 port=85800)_x000D_"
        "StartTime=2026-05-31 오전 4:15:02_x000D_"
        "PrivateMemorySize=64.12 MB_x000D_"
        "TimeAvg=0.07(1268), TimeMin=0, TimeMax=8"
    )

    assert normalize_log_text(first) == normalize_log_text(second)
    assert "pid" in normalize_log_text(first)
    assert "_x000D_" not in normalize_log_text(first)

    message = (
        "Start StaticPageInterface. "
        "functionConfigId : a2be9631-cf0e-4cdf-b132-7167dadd44d3,\n"
        " functionName : select_CurrentLineStepUserID"
    )
    normalized = normalize_log_text(message)

    assert "functionConfigId *" in normalized
    assert "functionName: select_CurrentLineStepUserID" in normalized


def test_fingerprint_normalizes_urls_paths_and_quoted_runtime_values() -> None:
    first = (
        "AbsoluteUri : http://test.com/test_appl/Main/View/123?token=abc "
        'Cannot convert "S970" into NUM '
        r"파일 E:\Test\30_Component\Test.Appl.Biz\LineBiz.cs:줄 94"
    )
    second = (
        "AbsoluteUri : http://test.com/test_appl/Main/View/456?token=def "
        'Cannot convert "S971" into NUM '
        r"파일 E:\Test\30_Component\Test.Appl.Biz\LineBiz.cs:줄 211"
    )

    normalized = normalize_log_text(first)

    assert normalize_log_text(first) == normalize_log_text(second)
    assert "AbsoluteUri: URL://test.com/test_appl/Main/View/*?token=*" in normalized
    assert 'Cannot convert "*"' in normalized
    assert "PATH\\LineBiz.cs" in normalized


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


def test_detection_pipeline_processes_only_new_raw_logs_and_tracks_metrics(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "billing-service",
                "ERROR",
                "Payment failed orderId=100",
                "",
                "2026-06-16T10:00:00",
            ),
        )
        conn.commit()

    first = run_detection_pipeline("billing-service")
    second = run_detection_pipeline("billing-service")

    assert first["summary"]["processed_new_logs"] == 1
    assert second["summary"]["processed_new_logs"] == 0
    assert second["fingerprints"][0]["occurrence_count"] == 1

    with sqlite3.connect(db_path) as conn:
        processed_count = conn.execute(
            "SELECT COUNT(*) FROM processed_log_offsets"
        ).fetchone()[0]
        metric_rows = conn.execute("""
            SELECT bucket_size, total_count, error_count
            FROM pattern_time_series_metrics
            ORDER BY bucket_size
            """).fetchall()

    assert processed_count == 1
    assert metric_rows == [("day", 1, 1), ("hour", 1, 1)]


def test_detection_pipeline_reports_spike_and_drop_anomaly_types(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    message = "Queue latency high queueId=42"

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        fp = fingerprint_id("queue-service", "ERROR", message, "")
        conn.execute(
            """
            INSERT INTO fingerprints(
                fingerprint, occurrence_count, log_level, message, stacktrace,
                service_name, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fp,
                20,
                "ERROR",
                message,
                "",
                "queue-service",
                "2026-06-14T00:00:00",
                "2026-06-15T23:59:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO log_analysis_results(
                fingerprint, category, sub_category, is_known_pattern, is_new_pattern,
                pattern_status, match_source, similar_fingerprint, similarity_score
            ) VALUES (?, 'Application', 'Queue', 0, 0, 'observed_existing', 'fingerprints', '', NULL)
            """,
            (fp,),
        )
        conn.executemany(
            """
            INSERT INTO pattern_time_series_metrics(
                service_name, fingerprint, bucket_start, bucket_size,
                total_count, error_count, warn_count, info_count, first_seen, last_seen
            ) VALUES (?, ?, ?, 'day', ?, ?, 0, 0, ?, ?)
            """,
            [
                (
                    "queue-service",
                    fp,
                    "2026-06-14",
                    10,
                    10,
                    "2026-06-14T00:00:00",
                    "2026-06-14T23:59:00",
                ),
                (
                    "queue-service",
                    fp,
                    "2026-06-15",
                    10,
                    10,
                    "2026-06-15T00:00:00",
                    "2026-06-15T23:59:00",
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "queue-service",
                    "ERROR",
                    f"Queue latency high queueId={idx}",
                    "",
                    f"2026-06-16T10:{idx:02d}:00",
                )
                for idx in range(20)
            ],
        )
        conn.commit()

    spike = run_detection_pipeline("queue-service")

    assert any(item["anomaly_type"] == "SPIKE" for item in spike["anomalies"])

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "queue-service",
                    "ERROR",
                    "Queue latency high queueId=900",
                    "",
                    "2026-06-17T10:00:00",
                ),
                (
                    "queue-service",
                    "ERROR",
                    "Queue latency high queueId=901",
                    "",
                    "2026-06-17T10:01:00",
                ),
            ],
        )
        conn.commit()

    drop = run_detection_pipeline("queue-service")

    assert any(item["anomaly_type"] == "DROP" for item in drop["anomalies"])


def test_detection_pipeline_hides_exception_fingerprints_from_clusters(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    ignored_message = (
        "테스트3님 권한이 없습니다. " "WorkID=552f54af-69e5-4f23-8402-6e9252bdad95"
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
    saved_documents = []

    def _fake_save_analysis_document(**kwargs):
        saved_documents.append(kwargs)
        return True

    monkeypatch.setattr(
        "app.db.scenario_store.save_analysis_document", _fake_save_analysis_document
    )
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
    approve_result(
        fingerprint,
        "permission denied",
        "check role mapping",
        "approved",
        "HIGH",
        "Granted the missing role and redeployed the service.",
    )

    exceptions = fetch_exception_registry(fingerprint=fingerprint)
    cards = fetch_knowledge_cards(fingerprint=fingerprint)

    assert exceptions[0]["message"] == message
    assert exceptions[0]["log_level"] == "WARN"
    assert cards[0]["message"] == message
    assert cards[0]["log_level"] == "WARN"
    assert cards[0]["title"].startswith("auth-service")
    assert (
        cards[0]["resolution_method"]
        == "Granted the missing role and redeployed the service."
    )
    assert "[Case Card]" in cards[0]["rag_document"]
    assert "[Resolution Method]" in cards[0]["rag_document"]
    assert (
        "Granted the missing role and redeployed the service."
        in cards[0]["rag_document"]
    )
    assert cards[0]["metadata"]["schema_version"] == "rag-case-card-v1"
    assert cards[0]["embedding_status"] == "embedded"
    assert saved_documents[0]["doc_id"].startswith("knowledge-card:KC-")
    assert saved_documents[0]["metadata"]["fingerprint"] == fingerprint
