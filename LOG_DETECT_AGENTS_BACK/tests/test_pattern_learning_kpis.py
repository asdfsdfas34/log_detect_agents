import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from app.db import scenario_store
from app.db.scenario_store import (
    clear_normalization_rule_cache,
    ensure_schema,
    fingerprint_id,
    run_detection_pipeline,
    save_pattern_normalization_rule,
)

DATASET_PATH = Path(__file__).parent / "fixtures" / "pattern_learning_kpi_dataset.json"
SERVICE_NAME = "pattern-learning-kpi"
LOG_LEVEL = "ERROR"
RULE_REGEX = r"^OrderSync region [A-Z]+ request=[a-z0-9-]+ retry=\d+ status=timeout$"
RULE_TEMPLATE = "OrderSync region * request=* retry=* status=timeout"


def _load_dataset() -> dict[str, Any]:
    with DATASET_PATH.open(encoding="utf-8") as dataset_file:
        return json.load(dataset_file)


def _alpha_suffix(index: int) -> str:
    return f"{chr(65 + (index // 26))}{chr(65 + (index % 26))}"


def _order_sync_messages(
    dataset: dict[str, Any], key: str, *, region_prefix: str
) -> list[str]:
    messages = list(dataset[key])
    target_count = int(dataset["target_count_per_kpi"])
    for index in range(len(messages), target_count):
        region = f"{region_prefix}{_alpha_suffix(index)}"
        messages.append(
            f"OrderSync region {region} request=req-{region.lower()} "
            f"retry={index + 1} status=timeout"
        )
    return messages


def _incremental_logs(dataset: dict[str, Any]) -> list[dict[str, str]]:
    logs = list(dataset["incremental_logs"])
    target_count = int(dataset["target_count_per_kpi"])
    for index in range(len(logs), target_count):
        logs.append(
            {
                "message": (
                    f"Worker heartbeat sequence={101 + index} "
                    f"node=node-{_alpha_suffix(index).lower()}"
                ),
                "created_at": f"2026-07-15T10:{index:02d}:00",
            }
        )
    return logs


def _prepare_database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    clear_normalization_rule_cache()
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
    return db_path


def _disable_external_similarity(monkeypatch: pytest.MonkeyPatch) -> None:
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


def _save_evaluation_rule() -> None:
    save_pattern_normalization_rule(
        name="order-sync-kpi-rule",
        match_regex=RULE_REGEX,
        template=RULE_TEMPLATE,
    )


def test_fingerprint_convergence_uses_fifty_labeled_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _prepare_database(tmp_path, monkeypatch)
    dataset = _load_dataset()
    messages = _order_sync_messages(
        dataset, "normalization_variants", region_prefix="NORM"
    )
    assert len(messages) == 50

    before = {
        fingerprint_id(SERVICE_NAME, LOG_LEVEL, message, "") for message in messages
    }
    assert len(before) == len(messages)

    _save_evaluation_rule()
    after = {
        fingerprint_id(SERVICE_NAME, LOG_LEVEL, message, "") for message in messages
    }
    convergence_rate = 1 - (len(after) / len(before))

    assert len(after) == 1
    assert convergence_rate >= 0.9


def test_known_pattern_reuse_uses_fifty_unseen_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _prepare_database(tmp_path, monkeypatch)
    _disable_external_similarity(monkeypatch)
    dataset = _load_dataset()
    messages = _order_sync_messages(
        dataset, "known_pattern_unseen_variants", region_prefix="UNSEEN"
    )
    assert len(messages) == 50

    _save_evaluation_rule()
    canonical_fingerprint = fingerprint_id(
        SERVICE_NAME, LOG_LEVEL, messages[0], ""
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO fingerprints(
                fingerprint, occurrence_count, log_level, message, stacktrace,
                service_name, first_seen, last_seen
            ) VALUES (?, 0, ?, ?, '', ?, ?, ?)
            """,
            (
                canonical_fingerprint,
                LOG_LEVEL,
                RULE_TEMPLATE,
                SERVICE_NAME,
                "2026-07-14T00:00:00",
                "2026-07-14T00:00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO known_patterns(
                fingerprint, category, sub_category, cause, recommendation, confidence
            ) VALUES (?, 'Integration', 'OrderSyncTimeout', ?, ?, 'HIGH')
            """,
            (
                canonical_fingerprint,
                "Approved OrderSync timeout pattern",
                "Check the OrderSync dependency and retry policy.",
            ),
        )
        conn.executemany(
            """
            INSERT INTO service_logs(
                service_name, level, message, stack_trace, created_at
            ) VALUES (?, ?, ?, '', ?)
            """,
            [
                (SERVICE_NAME, LOG_LEVEL, message, f"2026-07-15T11:{index:02d}:00")
                for index, message in enumerate(messages)
            ],
        )
        conn.commit()

    result = run_detection_pipeline(
        SERVICE_NAME,
        analysis_date="2026-07-15",
        include_time_windows=False,
    )
    fingerprint = result["fingerprints"][0]
    reuse_rate = fingerprint["occurrence_count"] / len(messages)

    assert result["summary"]["total_fingerprints"] == 1
    assert fingerprint["fingerprint"] == canonical_fingerprint
    assert fingerprint["pattern_status"] == "known_exact"
    assert reuse_rate >= 0.9


def test_incremental_processing_uses_fifty_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = _prepare_database(tmp_path, monkeypatch)
    _disable_external_similarity(monkeypatch)
    logs = _incremental_logs(_load_dataset())
    assert len(logs) == 50

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO service_logs(
                service_name, level, message, stack_trace, created_at
            ) VALUES (?, 'INFO', ?, '', ?)
            """,
            [(SERVICE_NAME, item["message"], item["created_at"]) for item in logs],
        )
        conn.commit()

    first = run_detection_pipeline(SERVICE_NAME, include_time_windows=False)
    second = run_detection_pipeline(SERVICE_NAME, include_time_windows=False)
    reduction_rate = 1 - (
        second["summary"]["processed_new_logs"]
        / first["summary"]["processed_new_logs"]
    )

    assert first["summary"]["processed_new_logs"] == len(logs)
    assert second["summary"]["processed_new_logs"] == 0
    assert second["summary"]["total_logs"] == len(logs)
    assert reduction_rate == 1.0
