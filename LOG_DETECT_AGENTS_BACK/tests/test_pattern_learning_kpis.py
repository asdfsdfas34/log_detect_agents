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
LOG_WIDTH = 76


def _log_header(sequence: str, title: str) -> None:
    print(f"\n{'=' * LOG_WIDTH}")
    print(f"[KPI {sequence}] {title}")
    print("=" * LOG_WIDTH)


def _log_step(number: int, message: str) -> None:
    print(f"  STEP {number}. {message}")


def _log_metric(label: str, value: str) -> None:
    print(f"    - {label:<28}: {value}")


def _log_pass(message: str) -> None:
    print(f"  RESULT  PASS - {message}")


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


def _new_anomaly_logs(dataset: dict[str, Any]) -> list[dict[str, str]]:
    logs = list(dataset["new_anomaly_logs"])
    target_count = int(dataset["target_count_per_kpi"])
    for index in range(len(logs), target_count):
        suffix = _alpha_suffix(index).lower()
        logs.append(
            {
                "message": (
                    f"Novel gateway failure signature=novel-{suffix} "
                    f"code=E{7001 + index} shard=shard-{suffix}"
                ),
                "created_at": f"2026-07-15T12:{index:02d}:00",
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
    _log_header("1/4", "Fingerprint 수렴률 검증")
    _prepare_database(tmp_path, monkeypatch)
    _log_step(1, "격리된 임시 SQLite 데이터베이스 초기화")

    dataset = _load_dataset()
    messages = _order_sync_messages(
        dataset, "normalization_variants", region_prefix="NORM"
    )
    _log_step(2, "동일 패턴의 라벨 변형 데이터 로드")
    _log_metric("평가 로그", f"{len(messages)}건")
    _log_metric("첫 번째 변형", messages[0])
    _log_metric("마지막 변형", messages[-1])
    assert len(messages) == 50

    before = {
        fingerprint_id(SERVICE_NAME, LOG_LEVEL, message, "") for message in messages
    }
    _log_step(3, "승인 규칙 적용 전 Fingerprint 생성")
    _log_metric("규칙 적용 전 고유 FP", f"{len(before)}개")
    assert len(before) == len(messages)

    _save_evaluation_rule()
    _log_step(4, "운영자 승인 normalization rule 저장 및 재적용")
    _log_metric("승인 rule", RULE_REGEX)
    _log_metric("canonical template", RULE_TEMPLATE)
    after = {
        fingerprint_id(SERVICE_NAME, LOG_LEVEL, message, "") for message in messages
    }
    convergence_rate = 1 - (len(after) / len(before))
    _log_step(5, "적용 전후 Fingerprint 수와 수렴률 비교")
    _log_metric("규칙 적용 후 고유 FP", f"{len(after)}개")
    _log_metric("수렴 결과", f"{len(before)}개 -> {len(after)}개")
    _log_metric("수렴률", f"{convergence_rate:.2%} (기준 >= 90%)")

    assert len(after) == 1
    assert convergence_rate >= 0.9
    _log_pass("50개 로그 변형이 canonical Fingerprint 1개로 수렴")


def test_known_pattern_detection_rate_uses_fifty_unseen_variants(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _log_header("2/4", "Known Pattern 재인식률 검증")
    db_path = _prepare_database(tmp_path, monkeypatch)
    _disable_external_similarity(monkeypatch)
    _log_step(1, "격리 DB 초기화 및 외부 유사도 검색을 테스트 대역으로 교체")

    dataset = _load_dataset()
    messages = _order_sync_messages(
        dataset, "known_pattern_unseen_variants", region_prefix="UNSEEN"
    )
    _log_step(2, "규칙 승인 과정에 사용하지 않은 신규 변형 데이터 로드")
    _log_metric("미노출 평가 로그", f"{len(messages)}건")
    assert len(messages) == 50

    _save_evaluation_rule()
    canonical_fingerprint = fingerprint_id(
        SERVICE_NAME, LOG_LEVEL, messages[0], ""
    )
    _log_step(3, "승인 rule과 canonical Known Pattern 등록")
    _log_metric("canonical Fingerprint", canonical_fingerprint)
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
    _log_step(4, "미노출 로그 50건을 service_logs에 저장")

    result = run_detection_pipeline(
        SERVICE_NAME,
        analysis_date="2026-07-15",
        include_time_windows=False,
    )
    fingerprint = result["fingerprints"][0]
    detection_rate = fingerprint["occurrence_count"] / len(messages)
    target_rate = float(dataset["kpi_targets"]["known_pattern_detection_rate"])
    _log_step(5, "탐지 파이프라인 실행 후 Known Pattern 판정 집계")
    _log_metric("처리 로그", f"{result['summary']['total_logs']}건")
    _log_metric("생성 Fingerprint", f"{result['summary']['total_fingerprints']}개")
    _log_metric("pattern_status", str(fingerprint["pattern_status"]))
    _log_metric("Known 판정 로그", f"{fingerprint['occurrence_count']}/{len(messages)}건")
    _log_metric("재인식률", f"{detection_rate:.2%} (기준 >= {target_rate:.0%})")

    assert result["summary"]["total_fingerprints"] == 1
    assert fingerprint["fingerprint"] == canonical_fingerprint
    assert fingerprint["pattern_status"] == "known_exact"
    assert detection_rate >= target_rate
    _log_pass("승인에 사용하지 않은 변형 50건을 Known Pattern으로 재인식")


def test_new_anomaly_identification_rate_uses_fifty_labeled_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _log_header("3/4", "신규 이상 징후 식별률 검증")
    db_path = _prepare_database(tmp_path, monkeypatch)
    _disable_external_similarity(monkeypatch)
    _log_step(1, "격리 DB 초기화 및 외부 유사도 검색을 테스트 대역으로 교체")

    dataset = _load_dataset()
    logs = _new_anomaly_logs(dataset)
    _log_step(2, "Known Pattern에 없는 신규 ERROR 라벨 데이터 로드")
    _log_metric("신규 이상 로그", f"{len(logs)}건")
    assert len(logs) == 50

    with sqlite3.connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO service_logs(
                service_name, level, message, stack_trace, created_at
            ) VALUES (?, 'ERROR', ?, '', ?)
            """,
            [(SERVICE_NAME, item["message"], item["created_at"]) for item in logs],
        )
        conn.commit()
    _log_step(3, "신규 ERROR 로그 50건을 service_logs에 저장")

    result = run_detection_pipeline(
        SERVICE_NAME,
        analysis_date="2026-07-15",
        include_time_windows=False,
    )
    identified_logs = sum(
        int(item["occurrence_count"])
        for item in result["fingerprints"]
        if item["pattern_status"] == "new_pattern"
    )
    identification_rate = identified_logs / len(logs)
    target_rate = float(dataset["kpi_targets"]["new_anomaly_identification_rate"])
    _log_step(4, "탐지 파이프라인 실행 후 new_pattern 발생 건수 집계")
    _log_metric("처리 로그", f"{result['summary']['total_logs']}건")
    _log_metric("new_pattern 식별", f"{identified_logs}/{len(logs)}건")
    _log_metric("식별률", f"{identification_rate:.2%} (기준 >= {target_rate:.0%})")

    assert result["summary"]["total_logs"] == len(logs)
    assert identification_rate >= target_rate
    _log_pass("신규 이상 로그 50건의 식별률이 목표 기준을 충족")


def test_incremental_processing_uses_fifty_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _log_header("4/4", "증분 분석 중복 재처리 절감률 검증")
    db_path = _prepare_database(tmp_path, monkeypatch)
    _disable_external_similarity(monkeypatch)
    _log_step(1, "격리 DB 초기화 및 외부 유사도 검색을 테스트 대역으로 교체")

    logs = _incremental_logs(_load_dataset())
    _log_step(2, "증분 처리 평가 로그 로드")
    _log_metric("평가 로그", f"{len(logs)}건")
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
    _log_step(3, "평가 로그 50건을 service_logs에 저장")

    _log_step(4, "동일 서비스 조건으로 탐지 파이프라인 2회 실행")
    first = run_detection_pipeline(SERVICE_NAME, include_time_windows=False)
    second = run_detection_pipeline(SERVICE_NAME, include_time_windows=False)
    reduction_rate = 1 - (
        second["summary"]["processed_new_logs"]
        / first["summary"]["processed_new_logs"]
    )
    _log_metric("1차 신규 처리", f"{first['summary']['processed_new_logs']}건")
    _log_metric("2차 신규 처리", f"{second['summary']['processed_new_logs']}건")
    _log_metric("저장 로그 유지", f"{second['summary']['total_logs']}건")
    _log_metric("중복 재처리 절감률", f"{reduction_rate:.2%}")

    assert first["summary"]["processed_new_logs"] == len(logs)
    assert second["summary"]["processed_new_logs"] == 0
    assert second["summary"]["total_logs"] == len(logs)
    assert reduction_rate == 1.0
    _log_pass("재실행에서 신규 처리 50건 -> 0건, 중복 재처리 100% 제거")
