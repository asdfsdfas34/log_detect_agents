import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from app.agents.pattern_rule_suggestion import PatternRuleSuggestionAgent
from app.db import scenario_store
from app.db.scenario_store import (
    approve_result,
    clear_normalization_rule_cache,
    detect_duplicate_pattern_candidates,
    ensure_schema,
    fetch_anomaly_daily_counts,
    fetch_duplicate_pattern_candidates,
    fetch_exception_registry,
    fetch_knowledge_cards,
    fingerprint_id,
    merge_duplicate_pattern_candidate,
    merge_selected_fingerprints_as_known_pattern,
    normalize_log_text,
    register_exception,
    run_detection_pipeline,
    save_pattern_normalization_rule,
    update_duplicate_pattern_candidate_status,
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
    clear_normalization_rule_cache()
    assert fingerprint_id("devops-service", "INFO", first, "") == fingerprint_id(
        "devops-service", "INFO", second, ""
    )


def test_approved_pattern_rule_groups_request_id_variants(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)

    first = (
        "DelayedApprovalNotiAgent.SendMail. To:test@test.com, "
        "DelayedApvCount:1, TotalWaitingApvCount:8 request_id=ed55e2346606"
    )
    second = (
        "DelayedApprovalNotiAgent.SendMail. To:test@test.com, "
        "DelayedApvCount:7, TotalWaitingApvCount:8"
    )
    assert normalize_log_text(first) != normalize_log_text(second)

    proposal = PatternRuleSuggestionAgent().propose(
        cluster="delayed-approval", message=first
    )
    save_pattern_normalization_rule(
        name=proposal.name,
        match_regex=proposal.match_regex,
        template=proposal.template,
    )

    assert normalize_log_text(first) == normalize_log_text(second)


def test_detection_pipeline_suggests_duplicate_pattern_candidates(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    messages = [
        (
            "SetImpersonation() userID:1111393, deptID:, "
            "CurrentUserInfo.UserID:1108366, CurrentUserInfo.ImpersonationAdminID"
        ),
        (
            "SetImpersonation() userID:1103450, deptID:, "
            "CurrentUserInfo.UserID:, CurrentUserInfo.ImpersonationAdminID"
        ),
        (
            "SetImpersonation() userID:1112074, deptID:00004787, "
            "CurrentUserInfo.UserID:, CurrentUserInfo.ImpersonationAdminID"
        ),
    ]
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('test_appl', 'information', ?, ?, ?)
            """,
            [
                (message, "", f"2026-06-16T10:0{index}:00")
                for index, message in enumerate(messages)
            ],
        )
        conn.commit()

    result = run_detection_pipeline("test_appl")

    candidates = result["duplicate_pattern_candidates"]
    assert len(result["fingerprints"]) == 3
    assert len(candidates) == 1
    assert len(candidates[0]["fingerprints"]) == 3
    assert candidates[0]["suggested_regex"].startswith("^SetImpersonation")
    assert candidates[0]["suggested_template"] == (
        "SetImpersonation() userID:* deptID:* "
        "CurrentUserInfo.UserID:* CurrentUserInfo.ImpersonationAdminID"
    )
    assert all(
        re.search(candidates[0]["suggested_regex"], message, flags=re.IGNORECASE)
        for message in messages
    )
    assert fetch_duplicate_pattern_candidates()[0]["candidate_key"] == candidates[0][
        "candidate_key"
    ]
    rule_id = save_pattern_normalization_rule(
        name="set-impersonation-merge",
        match_regex=candidates[0]["suggested_regex"],
        template=candidates[0]["suggested_template"],
    )
    update_duplicate_pattern_candidate_status(candidates[0]["candidate_key"], "approved")
    merge_result = merge_duplicate_pattern_candidate(
        candidates[0]["candidate_key"], rule_id=rule_id
    )

    assert merge_result["merged"] is True
    assert len(merge_result["merged_fingerprints"]) == 3
    with sqlite3.connect(db_path) as conn:
        fingerprint_rows = conn.execute(
            "SELECT fingerprint, occurrence_count FROM fingerprints"
        ).fetchall()
        alias_count = conn.execute("SELECT COUNT(*) FROM fingerprint_aliases").fetchone()[
            0
        ]
        known_count = conn.execute(
            "SELECT COUNT(*) FROM known_patterns WHERE fingerprint=?",
            (merge_result["canonical_fingerprint"],),
        ).fetchone()[0]
        result_row = conn.execute(
            """
            SELECT is_known_pattern, is_new_pattern, pattern_status, match_source
            FROM log_analysis_results
            WHERE fingerprint=?
            """,
            (merge_result["canonical_fingerprint"],),
        ).fetchone()
    assert fingerprint_rows == [
        (merge_result["canonical_fingerprint"], 3),
    ]
    assert alias_count == 3
    assert known_count == 1
    assert result_row == (1, 0, "known_exact", "known_patterns")
    assert all(
        fingerprint_id("test_appl", "INFORMATION", message, "")
        == merge_result["canonical_fingerprint"]
        for message in messages
    )
    legacy_wrong_fingerprint = fingerprint_id(
        "test_appl",
        "INFORMATION",
        candidates[0]["suggested_template"],
        candidates[0]["suggested_template"],
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE known_patterns SET fingerprint=? WHERE fingerprint=?",
            (legacy_wrong_fingerprint, merge_result["canonical_fingerprint"]),
        )
        conn.execute(
            "UPDATE fingerprints SET fingerprint=? WHERE fingerprint=?",
            (legacy_wrong_fingerprint, merge_result["canonical_fingerprint"]),
        )
        conn.execute(
            "UPDATE log_analysis_results SET fingerprint=? WHERE fingerprint=?",
            (legacy_wrong_fingerprint, merge_result["canonical_fingerprint"]),
        )
        conn.commit()
    rerun = run_detection_pipeline("test_appl", analysis_date="2026-06-16")
    assert rerun["summary"]["total_fingerprints"] == 1
    assert rerun["summary"]["known_patterns"] == 1
    assert rerun["summary"]["new_patterns"] == 0
    assert rerun["fingerprints"][0]["fingerprint"] == merge_result["canonical_fingerprint"]
    assert rerun["fingerprints"][0]["pattern_status"] == "known_exact"
    with sqlite3.connect(db_path) as conn:
        repaired_known_count = conn.execute(
            "SELECT COUNT(*) FROM known_patterns WHERE fingerprint=?",
            (merge_result["canonical_fingerprint"],),
        ).fetchone()[0]
    assert repaired_known_count == 1


def test_hybrid_similarity_promotes_structurally_identical_known_match(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        status = scenario_store._pattern_status_from_matches(
            conn=conn,
            item={
                "fingerprint": "FP-NEW",
                "service_name": "checkout-api",
                "log_level": "ERROR",
                "message": "Payment failed for order 123",
                "normalized_message": "payment failed for order <number>",
                "stacktrace": "",
            },
            existing_fingerprints=set(),
            approved_matches=[
                {
                    "id": "known-pattern:1",
                    "document": "payment failed for order <number>",
                    "metadata": {
                        "source": "known_pattern",
                        "fingerprint": "FP-OLD",
                        "service_name": "checkout-api",
                        "log_level": "ERROR",
                        "normalized_message": "payment failed for order <number>",
                    },
                    "similarity": 0.82,
                }
            ],
            observed_matches=[],
        )

    assert status["pattern_status"] == "known_similar"
    assert status["similar_fingerprint"] == "FP-OLD"
    assert status["similarity_score"] >= scenario_store.HYBRID_KNOWN_SIMILARITY_THRESHOLD


def test_high_embedding_similarity_does_not_override_low_pattern_similarity(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        status = scenario_store._pattern_status_from_matches(
            conn=conn,
            item={
                "fingerprint": "FP-NEW",
                "service_name": "checkout-api",
                "log_level": "ERROR",
                "message": "DB timeout while saving payment order 123",
                "normalized_message": "db timeout while saving payment order *",
                "stacktrace": "",
            },
            existing_fingerprints=set(),
            approved_matches=[
                {
                    "id": "known-pattern:1",
                    "document": "api timeout while calling partner callback",
                    "metadata": {
                        "source": "known_pattern",
                        "fingerprint": "FP-OLD",
                        "service_name": "checkout-api",
                        "log_level": "ERROR",
                        "normalized_message": "api timeout while calling partner callback",
                    },
                    "similarity": 0.94,
                }
            ],
            observed_matches=[],
        )

    assert status["pattern_status"] == "new_pattern"


def test_semantic_duplicate_groups_use_hybrid_score_below_raw_duplicate_threshold(
    monkeypatch,
) -> None:
    groups = [
        {
            "fingerprint": "FP-A",
            "service_name": "checkout-api",
            "log_level": "ERROR",
            "message": "Payment failed for order 123",
            "normalized_message": "payment failed for order <number>",
            "occurrence_count": 1,
        },
        {
            "fingerprint": "FP-B",
            "service_name": "checkout-api",
            "log_level": "ERROR",
            "message": "Payment failed for order 456",
            "normalized_message": "payment failed for order <number>",
            "occurrence_count": 1,
        },
    ]

    def fake_similar_batches(**kwargs: Any) -> list[list[dict[str, Any]]]:
        return [
            [
                {
                    "id": "checkout-api:FP-B",
                    "document": "payment failed for order <number>",
                    "metadata": {
                        "fingerprint": "FP-B",
                        "service_name": "checkout-api",
                        "log_level": "ERROR",
                        "normalized_message": "payment failed for order <number>",
                    },
                    "similarity": 0.90,
                }
            ],
            [
                {
                    "id": "checkout-api:FP-A",
                    "document": "payment failed for order <number>",
                    "metadata": {
                        "fingerprint": "FP-A",
                        "service_name": "checkout-api",
                        "log_level": "ERROR",
                        "normalized_message": "payment failed for order <number>",
                    },
                    "similarity": 0.90,
                }
            ],
        ]

    monkeypatch.setattr(
        scenario_store, "find_similar_pattern_clusters_batch", fake_similar_batches
    )

    semantic_groups = scenario_store._semantic_duplicate_groups(groups)

    assert len(semantic_groups) == 1
    assert {item["fingerprint"] for item in semantic_groups[0]} == {"FP-A", "FP-B"}


def test_hdbscan_duplicate_groups_use_optional_cluster_labels(monkeypatch) -> None:
    groups = [
        {"fingerprint": "FP-A", "service_name": "checkout-api", "log_level": "ERROR"},
        {"fingerprint": "FP-B", "service_name": "checkout-api", "log_level": "ERROR"},
        {"fingerprint": "FP-C", "service_name": "checkout-api", "log_level": "ERROR"},
    ]
    pair_scores = {
        ("FP-A", "FP-B"): 0.92,
        ("FP-A", "FP-C"): 0.91,
        ("FP-B", "FP-C"): 0.90,
    }
    monkeypatch.setattr(
        scenario_store,
        "_hdbscan_cluster_labels",
        lambda *args, **kwargs: [0, 0, 0],
    )

    semantic_groups = scenario_store._hdbscan_duplicate_groups(groups, pair_scores)

    assert len(semantic_groups) == 1
    assert {item["fingerprint"] for item in semantic_groups[0]} == {
        "FP-A",
        "FP-B",
        "FP-C",
    }


def test_semantic_log_clusters_fallback_to_drain_templates(monkeypatch) -> None:
    monkeypatch.setattr(scenario_store, "embed_pattern_texts_normalized", lambda texts: None)
    monkeypatch.setattr(
        scenario_store,
        "_mine_drain_templates",
        lambda messages: ["Payment failed for orderId=<*> request_id=<*>"]
        * len(messages),
    )
    groups = [
        {
            "fingerprint": "FP-A",
            "service_name": "checkout-api",
            "log_level": "ERROR",
            "message": "Payment failed for orderId=100 request_id=abc",
            "occurrence_count": 3,
            "pattern_status": "new_pattern",
        },
        {
            "fingerprint": "FP-B",
            "service_name": "checkout-api",
            "log_level": "ERROR",
            "message": "Payment failed for orderId=200 request_id=def",
            "occurrence_count": 2,
            "pattern_status": "new_pattern",
        },
    ]

    clusters = scenario_store.build_semantic_log_clusters(
        groups,
        recommendations=[
            {
                "fingerprint": "FP-A",
                "cause": "payment provider timeout",
                "recommendation": "review payment timeout handling",
            }
        ],
        impacts=[{"fingerprint": "FP-A", "risk_score": 70}],
    )

    assert len(clusters) == 1
    assert clusters[0]["algorithm"] == "drain3_template_fallback"
    assert clusters[0]["count"] == 5
    assert clusters[0]["fingerprints"] == ["FP-A", "FP-B"]
    assert clusters[0]["representative_cause"] == "payment provider timeout"
    assert "<*>" in clusters[0]["drain_template"]


def test_semantic_log_clusters_use_openai_umap_hdbscan_labels(monkeypatch) -> None:
    groups = [
        {
            "fingerprint": "FP-A",
            "service_name": "checkout-api",
            "log_level": "ERROR",
            "message": "Payment failed for orderId=100",
            "occurrence_count": 3,
        },
        {
            "fingerprint": "FP-B",
            "service_name": "checkout-api",
            "log_level": "ERROR",
            "message": "Payment failed for orderId=200",
            "occurrence_count": 2,
        },
        {
            "fingerprint": "FP-C",
            "service_name": "checkout-api",
            "log_level": "WARN",
            "message": "Cache warming delayed shard=7",
            "occurrence_count": 1,
        },
    ]
    monkeypatch.setattr(
        scenario_store,
        "embed_pattern_texts_normalized",
        lambda texts: [[1.0, 0.0], [0.99, 0.01], [0.0, 1.0]],
    )
    monkeypatch.setattr(
        scenario_store,
        "_semantic_cluster_labels_from_embeddings",
        lambda embeddings: ([0, 0, -1], "openai_l2_umap_hdbscan"),
    )

    clusters = scenario_store.build_semantic_log_clusters(groups)

    assert clusters[0]["algorithm"] == "openai_l2_umap_hdbscan"
    assert clusters[0]["fingerprint_count"] == 2
    assert clusters[0]["fingerprints"] == ["FP-A", "FP-B"]
    assert clusters[0]["representative_fingerprint"] == "FP-A"


def test_semantic_log_clusters_reuse_existing_drain_templates(monkeypatch) -> None:
    calls = 0

    def fake_mine(messages: list[str]) -> list[str]:
        nonlocal calls
        calls += 1
        return [f"template:{index}" for index, _ in enumerate(messages)]

    monkeypatch.setattr(scenario_store, "_mine_drain_templates", fake_mine)
    monkeypatch.setattr(scenario_store, "embed_pattern_texts_normalized", lambda texts: None)

    groups = [
        {
            "fingerprint": "FP-A",
            "service_name": "checkout-api",
            "log_level": "ERROR",
            "message": "Payment failed orderId=100",
            "drain_template": "Payment failed <*>",
            "occurrence_count": 2,
        },
        {
            "fingerprint": "FP-B",
            "service_name": "checkout-api",
            "log_level": "ERROR",
            "message": "Payment failed orderId=200",
            "drain_template": "Payment failed <*>",
            "occurrence_count": 1,
        },
    ]

    clusters = scenario_store.build_semantic_log_clusters(groups)

    assert calls == 0
    assert clusters[0]["drain_template"] == "Payment failed <*>"


def test_apply_drain_templates_creates_one_miner_batch(monkeypatch) -> None:
    batches: list[list[str]] = []

    def fake_mine(messages: list[str]) -> list[str]:
        batches.append(messages)
        return ["Payment failed <*>"] * len(messages)

    monkeypatch.setattr(scenario_store, "_mine_drain_templates", fake_mine)

    groups = [
        {"message": "Payment failed orderId=100"},
        {"message": "Payment failed orderId=200"},
        {"message": "Payment failed orderId=300"},
    ]

    enriched = scenario_store._apply_drain_templates(groups)

    assert len(batches) == 1
    assert len(batches[0]) == 3
    assert [item["drain_template"] for item in enriched] == [
        "Payment failed <*>",
        "Payment failed <*>",
        "Payment failed <*>",
    ]


def test_duplicate_candidate_groups_string_value_variants_after_approval(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    messages = [
        "BatchWorker failed functionName: AlphaJob reason=timeout",
        "BatchWorker failed functionName: AlphaJob reason=timeout",
        "BatchWorker failed functionName: BetaJob reason=timeout",
    ]
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('batch-service', 'ERROR', ?, '', ?)
            """,
            [
                (message, f"2026-07-01T09:0{index}:00")
                for index, message in enumerate(messages)
            ],
        )
        conn.commit()

    result = run_detection_pipeline("batch-service")

    candidates = result["duplicate_pattern_candidates"]
    assert len(result["fingerprints"]) == 2
    assert len(candidates) == 1
    assert len(result["fingerprint_merge_groups"]) == 1
    assert result["fingerprint_merge_groups"][0]["total_occurrence_count"] == 3
    assert result["event_time_windows"]
    assert result["system_state_vectors"]
    assert result["system_state_vectors"][0]["feature_schema_version"] == "system-state-v1"
    assert len(result["system_state_vectors"][0]["vector"]) == 10
    assert len(candidates[0]["fingerprints"]) == 2
    assert "functionName:*" in candidates[0]["suggested_template"]
    assert all(
        re.search(candidates[0]["suggested_regex"], message, flags=re.IGNORECASE)
        for message in messages
    )

    rule_id = save_pattern_normalization_rule(
        name="function-name-merge",
        match_regex=candidates[0]["suggested_regex"],
        template=candidates[0]["suggested_template"],
    )
    update_duplicate_pattern_candidate_status(candidates[0]["candidate_key"], "approved")
    merge_result = merge_duplicate_pattern_candidate(
        candidates[0]["candidate_key"], rule_id=rule_id
    )

    assert merge_result["merged"] is True
    assert merge_result["occurrence_count"] == 3
    rerun = run_detection_pipeline("batch-service", analysis_date="2026-07-01")
    assert rerun["summary"]["total_fingerprints"] == 1
    assert rerun["fingerprints"][0]["occurrence_count"] == 3


def test_manual_selected_fingerprint_merge_registers_known_pattern(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    first = (
        "PARAMETER I_SPERNR_TO of FUNCTION TEST_INT_ENTRUST_LIST (SETTER): "
        "cannot convert String into NUM(3)"
    )
    second = (
        "PARAMETER I_SPERNR_TO of FUNCTION TEST_INT_ENTRUST_LIST (SETTER): "
        "cannot convert String into NUM(5)"
    )
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO fingerprints(
                fingerprint, occurrence_count, log_level, message, stacktrace,
                service_name, first_seen, last_seen
            ) VALUES (?, ?, 'ERROR', ?, '', 'test_appl', ?, ?)
            """,
            [
                ("FP-B09568", 10, first, "2026-07-02T10:00:00", "2026-07-02T10:10:00"),
                ("FP-38AC10", 4, second, "2026-07-02T10:01:00", "2026-07-02T10:11:00"),
            ],
        )
        conn.commit()

    merge = merge_selected_fingerprints_as_known_pattern(
        service_name="test_appl",
        fingerprints=["FP-B09568", "FP-38AC10"],
        cause="Same ABAP function parameter conversion failure with variable NUM length.",
        recommendation="Treat NUM length as a variable template and review parameter mapping.",
    )

    assert merge["status"] == "merged"
    assert merge["canonical_fingerprint"]
    assert merge["known_pattern_id"]
    with sqlite3.connect(db_path) as conn:
        fingerprint_rows = conn.execute(
            "SELECT fingerprint, occurrence_count FROM fingerprints"
        ).fetchall()
        alias_count = conn.execute("SELECT COUNT(*) FROM fingerprint_aliases").fetchone()[
            0
        ]
        known_count = conn.execute(
            "SELECT COUNT(*) FROM known_patterns WHERE fingerprint=?",
            (merge["canonical_fingerprint"],),
        ).fetchone()[0]
        result_row = conn.execute(
            """
            SELECT is_known_pattern, is_new_pattern, pattern_status, match_source
            FROM log_analysis_results
            WHERE fingerprint=?
            """,
            (merge["canonical_fingerprint"],),
        ).fetchone()
    assert fingerprint_rows == [(merge["canonical_fingerprint"], 14)]
    assert alias_count >= 1
    assert known_count >= 1
    assert result_row == (1, 0, "known_exact", "known_patterns")


def test_duplicate_candidates_use_chroma_similarity_for_near_patterns(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
    groups = [
        {
            "fingerprint": "FP-EBF7E1",
            "service_name": "test_appl",
            "log_level": "INFORMATION",
            "message": (
                "FTP 다운로드(FtpClient) 시도(0) / "
                "/TEST_/erp_user/EA/NEW/WORKFLOW/WTR202606000007.TXT => "
                "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\a.file"
            ),
            "stacktrace": "",
            "occurrence_count": 1,
        },
        {
            "fingerprint": "FP-6D1E73",
            "service_name": "test_appl",
            "log_level": "INFORMATION",
            "message": (
                "FTP 다운로드(FtpClient) 시도(0) / "
                "/TEST_/erp_user/EA/NEW/CONTENTS/TR202606000007_IND.xml => "
                "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\b.file"
            ),
            "stacktrace": "",
            "occurrence_count": 1,
        },
    ]

    def fake_similar_batches(queries: list[str], n_results: int = 5):
        return [
            [{"metadata": {"fingerprint": "FP-6D1E73"}, "similarity": 0.98}],
            [{"metadata": {"fingerprint": "FP-EBF7E1"}, "similarity": 0.98}],
        ]

    monkeypatch.setattr(
        scenario_store, "find_similar_pattern_clusters_batch", fake_similar_batches
    )

    candidates = detect_duplicate_pattern_candidates(groups)

    assert len(candidates) == 1
    assert candidates[0]["fingerprints"] == ["FP-6D1E73", "FP-EBF7E1"]
    assert "/TEST_/erp_user/EA/NEW/*/*" in candidates[0]["suggested_template"]
    assert all(
        re.search(
            candidates[0]["suggested_regex"],
            str(group["message"]),
            flags=re.IGNORECASE,
        )
        for group in groups
    )
    assert candidates[0]["confidence"] > 0.87


def test_duplicate_candidates_reject_semantic_similarity_without_pattern_match(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    groups = [
        {
            "fingerprint": "FP-2AC59D",
            "service_name": "test_appl",
            "log_level": "INFORMATION",
            "message": (
                "FTP download(FtpClient) attempt(0) / "
                "/TEST_/erp_user/EA/NEW/WORKFLOW/WTR202606000007.TXT => "
                "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\a.file"
            ),
            "stacktrace": "",
            "occurrence_count": 1,
        },
        {
            "fingerprint": "FP-451DF2",
            "service_name": "test_appl",
            "log_level": "INFORMATION",
            "message": (
                "FTP download(FtpClient) try(0) / "
                "/TEST_/erp_user/EA/NEW/CONTENTS/TR202606000007_IND.xml => "
                "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\b.file"
            ),
            "stacktrace": "",
            "occurrence_count": 1,
        },
    ]

    def fake_similar_batches(queries: list[str], n_results: int = 5):
        return [
            [{"metadata": {"fingerprint": "FP-451DF2"}, "similarity": 0.94}],
            [{"metadata": {"fingerprint": "FP-2AC59D"}, "similarity": 0.94}],
        ]

    monkeypatch.setattr(
        scenario_store, "find_similar_pattern_clusters_batch", fake_similar_batches
    )

    candidates = detect_duplicate_pattern_candidates(groups)

    assert candidates == []


def test_approved_semantic_duplicate_aliases_are_known_on_date_rerun(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    messages = [
        (
            "FTP ?ㅼ슫濡쒕뱶(FtpClient) ?쒕룄(0) / "
            "/TEST_/erp_user/EA/NEW/WORKFLOW/WTR202606000007.TXT => "
            "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\a.file"
        ),
        (
            "FTP ?ㅼ슫濡쒕뱶(FtpClient) ?쒕룄(0) / "
            "/TEST_/erp_user/EA/NEW/CONTENTS/TR202606000007_IND.xml => "
            "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\b.file"
        ),
        (
            "FTP ?ㅼ슫濡쒕뱶(FtpClient) ?쒕룄(0) / "
            "/TEST_/erp_user/EA/NEW/APPROVAL/APV202606000007.TXT => "
            "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\c.file"
        ),
        (
            "FTP ?ㅼ슫濡쒕뱶(FtpClient) ?쒕룄(0) / "
            "/TEST_/erp_user/EA/NEW/BOARD/BD202606000007.xml => "
            "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\d.file"
        ),
    ]

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('test_appl', 'information', ?, '', ?)
            """,
            [
                (message, f"2026-06-30T09:0{index}:00")
                for index, message in enumerate(messages)
            ],
        )
        conn.commit()

    def fake_similar_batches(queries: list[str], n_results: int = 5):
        fingerprints = [
            fingerprint_id("test_appl", "INFORMATION", message, "")
            for message in messages
        ]
        return [
            [
                {
                    "id": f"test_appl:{other}",
                    "metadata": {"fingerprint": other},
                    "similarity": 0.98,
                }
                for other in fingerprints
                if other != fingerprints[index]
            ][:n_results]
            for index, _query in enumerate(queries)
        ]

    monkeypatch.setattr(
        scenario_store, "find_similar_pattern_clusters_batch", fake_similar_batches
    )

    result = run_detection_pipeline("test_appl", analysis_date="2026-06-30")
    candidate = result["duplicate_pattern_candidates"][0]
    rule_id = save_pattern_normalization_rule(
        name="ftp-semantic-duplicate",
        match_regex=candidate["suggested_regex"],
        template=candidate["suggested_template"],
    )
    update_duplicate_pattern_candidate_status(candidate["candidate_key"], "approved")
    merge_result = merge_duplicate_pattern_candidate(
        candidate["candidate_key"], rule_id=rule_id
    )

    assert merge_result["merged"] is True
    assert len(merge_result["merged_fingerprints"]) == 4

    with sqlite3.connect(db_path) as conn:
        merge_group_count = conn.execute(
            "SELECT COUNT(*) FROM fingerprint_merge_groups"
        ).fetchone()[0]
        merge_group_status = conn.execute(
            "SELECT status FROM fingerprint_merge_groups"
        ).fetchone()[0]
        window_count = conn.execute("SELECT COUNT(*) FROM event_time_windows").fetchone()[0]
        vector_count = conn.execute(
            "SELECT COUNT(*) FROM system_state_vectors"
        ).fetchone()[0]
        conn.execute(
            """
            UPDATE pattern_duplicate_candidates
            SET suggested_regex='a^'
            WHERE candidate_key=?
            """,
            (candidate["candidate_key"],),
        )
        conn.execute(
            "UPDATE pattern_normalization_rules SET enabled=0 WHERE id=?",
            (rule_id,),
        )
        conn.commit()
    assert merge_group_count == 1
    assert merge_group_status == "approved"
    assert window_count > 0
    assert vector_count > 0
    clear_normalization_rule_cache()

    rerun = run_detection_pipeline("test_appl", analysis_date="2026-06-30")

    assert rerun["summary"]["total_fingerprints"] == 1
    assert rerun["summary"]["known_patterns"] == 1
    assert rerun["summary"]["new_patterns"] == 0
    assert rerun["fingerprints"][0]["fingerprint"] == merge_result["canonical_fingerprint"]
    assert rerun["fingerprints"][0]["pattern_status"] == "known_exact"


def test_known_pattern_signature_absorbs_new_raw_fingerprints_on_date_analysis(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    canonical_fp = "FP-E0F041"
    canonical_message = (
        "FTP 다운로드(FtpClient) 시도(*) / /TEST_/erp_user/EA/NEW/*/* = * PATH\\*.file"
    )
    messages = [
        (
            "FTP 다운로드(FtpClient) 시도(0) / "
            "/TEST_/erp_user/EA/NEW/WORKFLOW/WMM202606000001.TXT => "
            "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\a.file"
        ),
        (
            "FTP 다운로드(FtpClient) 시도(0) / "
            "/TEST_/erp_user/EA/NEW/APPROVAL/AMM202606000001.TXT => "
            "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\b.file"
        ),
        (
            "FTP 다운로드(FtpClient) 시도(0) / "
            "/TEST_/erp_user/EA/NEW/CONTENTS/MM202606000001_IND.xml => "
            "E:\\Test.Appl.Solutions\\Storage\\Disk_FU_Temporary\\EDMS\\ERP\\hash\\c.file"
        ),
    ]
    raw_fingerprints = {
        fingerprint_id("test_appl", "INFORMATION", message, "") for message in messages
    }
    assert canonical_fp not in raw_fingerprints
    assert len(raw_fingerprints) == len(messages)

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO fingerprints(
                fingerprint, occurrence_count, log_level, message, stacktrace,
                service_name, first_seen, last_seen
            ) VALUES (?, 4, 'INFORMATION', ?, '', 'test_appl',
                      '2026-06-27T00:00:00', '2026-06-27T00:00:00')
            """,
            (canonical_fp, canonical_message),
        )
        conn.execute(
            """
            INSERT INTO known_patterns(
                fingerprint, category, sub_category, cause, recommendation, confidence
            ) VALUES (?, 'Manual', 'Merged Duplicate Pattern',
                      'Approved duplicate pattern candidate DUP-FTP',
                      'Pattern normalization rule groups duplicate fingerprints.', 'HIGH')
            """,
            (canonical_fp,),
        )
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('test_appl', 'information', ?, '', ?)
            """,
            [
                (message, f"2026-06-28T10:0{index}:00")
                for index, message in enumerate(messages)
            ],
        )
        conn.commit()

    monkeypatch.setattr(
        scenario_store,
        "find_similar_analysis_documents_batch",
        lambda queries: [[] for _ in queries],
    )
    monkeypatch.setattr(
        scenario_store,
        "find_similar_pattern_clusters_batch",
        lambda queries: [[] for _ in queries],
    )

    result = run_detection_pipeline("test_appl", analysis_date="2026-06-28")

    assert result["summary"]["total_fingerprints"] == 1
    assert result["summary"]["known_patterns"] == 1
    assert result["summary"]["new_patterns"] == 0
    assert result["fingerprints"][0]["fingerprint"] == canonical_fp
    assert result["fingerprints"][0]["occurrence_count"] == len(messages)
    assert result["fingerprints"][0]["pattern_status"] == "known_exact"
    assert result["fingerprints"][0]["match_source"] == "known_patterns"


def test_approved_duplicate_candidate_rerun_uses_raw_stacktrace(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    messages = [
        (
            "SetImpersonation() userID:1111393, deptID:, "
            "CurrentUserInfo.UserID:1108366, CurrentUserInfo.ImpersonationAdminID"
        ),
        (
            "SetImpersonation() userID:1103450, deptID:, "
            "CurrentUserInfo.UserID:, CurrentUserInfo.ImpersonationAdminID"
        ),
    ]
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('test_appl', 'information', ?, ?, ?)
            """,
            [
                (message, message, f"2026-06-16T11:0{index}:00")
                for index, message in enumerate(messages)
            ],
        )
        conn.commit()

    result = run_detection_pipeline("test_appl")
    candidate = result["duplicate_pattern_candidates"][0]
    rule_id = save_pattern_normalization_rule(
        name="set-impersonation-stack-merge",
        match_regex=candidate["suggested_regex"],
        template=candidate["suggested_template"],
    )
    update_duplicate_pattern_candidate_status(candidate["candidate_key"], "approved")
    merge_result = merge_duplicate_pattern_candidate(
        candidate["candidate_key"], rule_id=rule_id
    )

    assert merge_result["merged"] is True
    assert all(
        fingerprint_id("test_appl", "INFORMATION", message, message)
        == merge_result["canonical_fingerprint"]
        for message in messages
    )
    rerun = run_detection_pipeline("test_appl", analysis_date="2026-06-16")
    assert rerun["summary"]["total_fingerprints"] == 1
    assert rerun["summary"]["known_patterns"] == 1
    assert rerun["summary"]["new_patterns"] == 0
    assert rerun["fingerprints"][0]["fingerprint"] == merge_result["canonical_fingerprint"]
    assert rerun["fingerprints"][0]["pattern_status"] == "known_exact"


def test_manual_merge_rescues_unmatched_regex_with_raw_logs(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    first_message = (
        'Test.Appl.InterfaceWeb.ApvInterfaceException: 결재선(Line)의 사용자(1103853) '
        '정보가 존재하지 않습니다. 수신된 데이터: {"LineType":"1000","ApvType":"9000",'
        '"StepOrder":"0001","UserId":"1103853","DeptId":"00004791"} _x000D_'
    )
    second_message = (
        'Test.Appl.InterfaceWeb.ApvInterfaceException: 결재선(Line)의 사용자(5205701) '
        '정보가 존재하지 않습니다. 수신된 데이터: {"LineType":"1000","ApvType":"1000",'
        '"StepOrder":"0001","UserId":"5205701","DeptId":""} _x000D_'
    )
    first_stack = "위치: Test.Appl.InterfaceWeb.Filters.DocumentCreationValidationActionFilter"
    second_stack = "위치: Test.Appl.InterfaceWeb.Filters.DocumentCreationValidationFilter"
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('test_appl', 'information', ?, ?, ?)
            """,
            [
                (first_message, first_stack, "2026-06-18T10:00:00"),
                *[
                    (second_message, second_stack, f"2026-06-18T10:0{index}:00")
                    for index in range(1, 8)
                ],
            ],
        )
        conn.commit()

    result = run_detection_pipeline("test_appl", analysis_date="2026-06-18")
    selected = sorted(item["fingerprint"] for item in result["fingerprints"])
    assert len(selected) == 2
    assert sorted(item["occurrence_count"] for item in result["fingerprints"]) == [1, 7]
    candidate_key = "DUP-MANUAL-RAW-RESCUE"
    template = (
        'Test.Appl.InterfaceWeb.ApvInterfaceException:* 사용자(*) 정보가 존재하지 않습니다. '
        '수신된 데이터:{"LineType":"*" "ApvType":"*" "StepOrder":"*" '
        '"UserId":"*" "DeptId":"*"} *'
    )
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO pattern_duplicate_candidates(
                candidate_key, service_name, log_level, signature,
                fingerprints_json, suggested_regex, suggested_template,
                confidence, reason, status
            ) VALUES (?, 'test_appl', 'INFORMATION', ?, ?, '^does-not-match$',
                      ?, 0.99, 'manual rescue test', 'approved')
            """,
            (candidate_key, template, json.dumps(selected), template),
        )
        conn.commit()
    rule_id = save_pattern_normalization_rule(
        name="manual-raw-rescue",
        match_regex="^does-not-match$",
        template=template,
    )

    merge_result = merge_duplicate_pattern_candidate(candidate_key, rule_id=rule_id)

    assert merge_result["merged"] is True
    assert merge_result["occurrence_count"] == 8
    assert len(merge_result["merged_fingerprints"]) == 2
    with sqlite3.connect(db_path) as conn:
        saved_regex = conn.execute(
            "SELECT match_regex FROM pattern_normalization_rules WHERE id=?",
            (rule_id,),
        ).fetchone()[0]
    assert saved_regex != "^does-not-match$"
    rerun = run_detection_pipeline("test_appl", analysis_date="2026-06-18")
    assert rerun["summary"]["total_fingerprints"] == 1
    assert rerun["fingerprints"][0]["fingerprint"] == merge_result["canonical_fingerprint"]
    assert rerun["fingerprints"][0]["occurrence_count"] == 8
    assert rerun["fingerprints"][0]["pattern_status"] == "known_exact"


def test_approved_duplicate_candidate_from_date_analysis_becomes_known(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    messages = [
        (
            "SetImpersonation() userID:1111393, deptID:, "
            "CurrentUserInfo.UserID:1108366, CurrentUserInfo.ImpersonationAdminID"
        ),
        (
            "SetImpersonation() userID:1103450, deptID:, "
            "CurrentUserInfo.UserID:, CurrentUserInfo.ImpersonationAdminID"
        ),
        (
            "SetImpersonation() userID:1112074, deptID:00004787, "
            "CurrentUserInfo.UserID:, CurrentUserInfo.ImpersonationAdminID"
        ),
    ]
    suffixed_messages = [
        f"{messages[0]} request_id=abc123",
        f"{messages[1]} sample_seq=42",
    ]
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('test_appl', 'information', ?, '', ?)
            """,
            [
                (message, f"2026-06-16T12:0{index}:00")
                for index, message in enumerate(messages)
            ],
        )
        conn.commit()

    result = run_detection_pipeline("test_appl", analysis_date="2026-06-16")
    candidate = result["duplicate_pattern_candidates"][0]
    with sqlite3.connect(db_path) as conn:
        persisted_fingerprint_count = conn.execute(
            "SELECT COUNT(*) FROM fingerprints"
        ).fetchone()[0]
    assert persisted_fingerprint_count == 3
    fetched_candidate = fetch_duplicate_pattern_candidates()[0]
    assert all(
        fetched_candidate["fingerprint_details"][fingerprint].get("message")
        for fingerprint in candidate["fingerprints"]
    )

    rule_id = save_pattern_normalization_rule(
        name="date-analysis-duplicate",
        match_regex=candidate["suggested_regex"],
        template=candidate["suggested_template"],
    )
    update_duplicate_pattern_candidate_status(candidate["candidate_key"], "approved")
    merge_result = merge_duplicate_pattern_candidate(
        candidate["candidate_key"], rule_id=rule_id
    )

    assert merge_result["merged"] is True
    assert merge_result["occurrence_count"] == 3
    with sqlite3.connect(db_path) as conn:
        known_count = conn.execute(
            "SELECT COUNT(*) FROM known_patterns WHERE fingerprint=?",
            (merge_result["canonical_fingerprint"],),
        ).fetchone()[0]
    assert known_count == 1

    save_pattern_normalization_rule(
        name="older-broad-conflicting-rule",
        match_regex=r"^SetImpersonation\(\).*$",
        template="SetImpersonation() legacy:*",
        priority=9999,
    )
    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('test_appl', 'information', ?, '', ?)
            """,
            [
                (message, f"2026-06-16T12:1{index}:00")
                for index, message in enumerate(suffixed_messages)
            ],
        )
        conn.commit()
    rerun = run_detection_pipeline("test_appl", analysis_date="2026-06-16")
    assert rerun["duplicate_pattern_candidates"] == []
    assert rerun["summary"]["total_fingerprints"] == 1
    assert rerun["summary"]["known_patterns"] == 1
    assert rerun["summary"]["new_patterns"] == 0
    assert rerun["fingerprints"][0]["fingerprint"] == merge_result["canonical_fingerprint"]
    assert rerun["fingerprints"][0]["pattern_status"] == "known_exact"
    assert rerun["fingerprints"][0]["match_source"] == "known_patterns"


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


def test_detection_pipeline_filters_service_logs_by_analysis_date(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    "payment-api",
                    "ERROR",
                    "target day failure",
                    "",
                    "2026-06-16T10:00:00",
                ),
                (
                    "payment-api",
                    "ERROR",
                    "other day failure",
                    "",
                    "2026-06-17T10:00:00",
                ),
                (
                    "auth-service",
                    "ERROR",
                    "other service failure",
                    "",
                    "2026-06-16 10:00:00",
                ),
            ],
        )
        conn.commit()

    result = run_detection_pipeline("payment-api", analysis_date="2026-06-16")

    assert result["summary"]["total_logs"] == 1
    assert result["summary"]["processed_new_logs"] == 1
    assert result["fingerprints"][0]["message"] == "target day failure"
    assert result["summary"]["new_patterns"] == 1
    assert result["summary"]["anomalies_detected"] == 0
    assert result["anomalies"] == []
    assert result["anomaly_daily_counts"] == [
        {
            "service_name": "payment-api",
            "analysis_date": "2026-06-16",
            "anomaly_count": 0,
        }
    ]
    assert fetch_anomaly_daily_counts("payment-api") == result[
        "anomaly_daily_counts"
    ]


def test_known_similar_is_not_reported_as_anomaly() -> None:
    anomaly, anomaly_type, severity = scenario_store._anomaly_type_for(
        group={"pattern_status": "known_similar", "log_level": "ERROR"},
        known=True,
        spike_ratio=100.0,
        metric={"latest_count": 1, "baseline_count": 0.0},
    )

    assert anomaly is False
    assert anomaly_type == "NONE"
    assert severity == "NONE"


def test_known_pattern_recurrence_requires_one_week_silence() -> None:
    anomaly, anomaly_type, severity = scenario_store._anomaly_type_for(
        group={
            "pattern_status": "known_exact",
            "log_level": "ERROR",
            "previous_last_seen": "2026-06-01T00:00:00",
            "first_seen": "2026-06-07T23:59:59",
        },
        known=True,
        spike_ratio=100.0,
        metric={"latest_count": 1, "baseline_count": 0.0},
    )

    assert anomaly is False
    assert anomaly_type == "NONE"
    assert severity == "NONE"

    anomaly, anomaly_type, severity = scenario_store._anomaly_type_for(
        group={
            "pattern_status": "known_exact",
            "log_level": "ERROR",
            "previous_last_seen": "2026-06-01T00:00:00",
            "first_seen": "2026-06-08T00:00:00",
        },
        known=True,
        spike_ratio=100.0,
        metric={"latest_count": 1, "baseline_count": 0.0},
    )

    assert anomaly is True
    assert anomaly_type == "RECURRENCE"
    assert severity == "MEDIUM"


def test_observed_existing_is_not_recurrence_without_known_status() -> None:
    anomaly, anomaly_type, severity = scenario_store._anomaly_type_for(
        group={
            "pattern_status": "observed_existing",
            "log_level": "ERROR",
            "previous_last_seen": "2026-06-01T00:00:00",
            "first_seen": "2026-06-10T00:00:00",
        },
        known=False,
        spike_ratio=100.0,
        metric={"latest_count": 1, "baseline_count": 0.0},
    )

    assert anomaly is False
    assert anomaly_type == "NONE"
    assert severity == "NONE"


def test_observed_existing_keeps_similarity_score_for_display() -> None:
    with sqlite3.connect(":memory:") as conn:
        ensure_schema(conn)
        result = scenario_store._pattern_status_from_matches(
            conn=conn,
            item={
                "service_name": "payment-api",
                "fingerprint": "FP-NEW",
            },
            existing_fingerprints={"FP-NEW"},
            approved_matches=[],
            observed_matches=[
                {
                    "id": "payment-api:FP-OLD",
                    "metadata": {"fingerprint": "FP-OLD"},
                    "similarity": 0.72,
                }
            ],
        )

    assert result["pattern_status"] == "observed_existing"
    assert result["similar_fingerprint"] == "FP-OLD"
    assert result["similarity_score"] == 0.72


def test_observed_existing_exact_rerun_defaults_similarity_to_full_match() -> None:
    with sqlite3.connect(":memory:") as conn:
        ensure_schema(conn)
        result = scenario_store._pattern_status_from_matches(
            conn=conn,
            item={
                "service_name": "payment-api",
                "fingerprint": "FP-EXISTING",
            },
            existing_fingerprints={"FP-EXISTING"},
            approved_matches=[],
            observed_matches=[],
        )

    assert result["pattern_status"] == "observed_existing"
    assert result["similarity_score"] == 1.0


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


def test_detection_pipeline_can_skip_time_window_modeling(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.execute(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('billing-service', 'ERROR', 'Payment failed orderId=100', '', ?)
            """,
            ("2026-06-16T10:00:00",),
        )
        conn.commit()

    result = run_detection_pipeline("billing-service", include_time_windows=False)

    assert result["event_time_windows"] == []
    assert result["system_state_vectors"] == []
    with sqlite3.connect(db_path) as conn:
        window_count = conn.execute("SELECT COUNT(*) FROM event_time_windows").fetchone()[0]
        vector_count = conn.execute("SELECT COUNT(*) FROM system_state_vectors").fetchone()[0]

    assert window_count == 0
    assert vector_count == 0


def test_time_window_modeling_reuses_recent_bounded_windows_on_rerun(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('billing-service', 'ERROR', ?, '', ?)
            """,
            [
                (f"Payment failed orderId={index}", f"2026-06-16T10:{index:02d}:00")
                for index in range(3)
            ],
        )
        conn.commit()

    first = run_detection_pipeline("billing-service")
    second = run_detection_pipeline("billing-service")

    assert first["event_time_windows"]
    assert first["system_state_vectors"]
    assert second["summary"]["processed_new_logs"] == 0
    assert second["event_time_windows"]
    assert second["system_state_vectors"]
    assert len(second["event_time_windows"]) <= scenario_store.TIME_WINDOW_RETURN_LIMIT
    assert len(second["system_state_vectors"]) <= scenario_store.TIME_WINDOW_RETURN_LIMIT


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
