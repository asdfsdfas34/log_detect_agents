"""Run a paired recommendation-quality ablation with and without similarity evidence.

This script intentionally performs live LLM calls. It is not part of the automated pytest
suite. Run it manually from the backend project directory.
"""

from __future__ import annotations

import json
import os
import random
import statistics
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.agents.recommendation import RecommendationAgent
from app.config import settings
from app.llm import openai_client
from app.mcp import get_mcp_client


@dataclass(frozen=True)
class IncidentCase:
    case_id: str
    service: str
    fingerprint: str
    message: str
    component: str
    cause_hint: str
    action_hint: str
    metric: str
    card_id: str
    similar_resolution: str


CASES = [
    IncidentCase(
        "timeout",
        "payment-api",
        "fp-payment-provider-timeout",
        "payment provider timeout after 5000ms",
        "PaymentClient.call",
        "외부 결제사 응답 지연",
        "timeout 및 제한된 retry 정책 검토",
        "provider_timeout_rate",
        "KC-PAY-101",
        "provider 지연 구간을 확인하고 timeout·retry 상한을 검증한 뒤 단계적으로 반영",
    ),
    IncidentCase(
        "db-pool",
        "order-api",
        "fp-db-pool-exhausted",
        "database connection pool exhausted",
        "OrderRepository.save",
        "장시간 점유된 DB connection 증가",
        "connection 반환 누락과 query duration 점검",
        "db_pool_wait_ms",
        "KC-DB-204",
        "slow query와 connection 반환 경로를 추적하고 pool wait 경보를 추가",
    ),
    IncidentCase(
        "redis",
        "session-api",
        "fp-redis-read-timeout",
        "redis read timeout after 2000ms",
        "SessionStore.get",
        "Redis 응답 지연 또는 hot key 집중",
        "hot key와 command latency 확인",
        "redis_command_latency_ms",
        "KC-REDIS-033",
        "hot key 분포와 command latency를 함께 확인하고 캐시 실패 동작을 검증",
    ),
    IncidentCase(
        "kafka-lag",
        "settlement-worker",
        "fp-kafka-consumer-lag",
        "consumer lag exceeded 120000 messages",
        "SettlementConsumer.poll",
        "처리량 저하로 consumer lag 누적",
        "처리 지연 구간과 retry backlog 조사",
        "consumer_lag",
        "KC-KAFKA-078",
        "partition별 lag와 처리시간을 비교하고 poison message 격리 여부를 확인",
    ),
    IncidentCase(
        "auth",
        "auth-api",
        "fp-jwt-validation-failed",
        "jwt validation failed: key id not found",
        "JwtVerifier.verify",
        "배포 시점의 key-id 불일치 가능성",
        "key-id 조회와 배포 설정 일치 여부 확인",
        "jwt_validation_failure_rate",
        "KC-AUTH-052",
        "배포 전후 key-id 분포와 verifier 설정을 비교하고 이전 key 호환성을 검증",
    ),
    IncidentCase(
        "memory",
        "catalog-api",
        "fp-heap-pressure",
        "heap usage above 92 percent with repeated full gc",
        "CatalogCache.refresh",
        "대형 cache refresh 객체의 수명 증가",
        "heap histogram과 refresh batch 크기 확인",
        "full_gc_count",
        "KC-JVM-119",
        "heap histogram과 refresh 실행 시점을 대조해 잔존 객체와 batch 크기를 검증",
    ),
    IncidentCase(
        "disk",
        "log-indexer",
        "fp-disk-write-failed",
        "index segment write failed: no space left",
        "SegmentWriter.flush",
        "segment 또는 임시 파일 증가",
        "segment 생성량과 임시 파일 정리 상태 확인",
        "disk_free_percent",
        "KC-DISK-041",
        "segment 증가율과 보존 정책 동작을 확인하고 임계치 경보를 검증",
    ),
    IncidentCase(
        "upstream-5xx",
        "gateway-api",
        "fp-upstream-503",
        "upstream returned 503 for inventory endpoint",
        "InventoryProxy.forward",
        "inventory-api 가용성 저하",
        "upstream 상태와 gateway retry 분포 확인",
        "upstream_5xx_rate",
        "KC-GW-066",
        "upstream 5xx와 retry 횟수를 함께 분석하고 fallback 응답을 검증",
    ),
    IncidentCase(
        "deadlock",
        "billing-api",
        "fp-transaction-deadlock",
        "transaction deadlock detected while updating invoice",
        "InvoiceRepository.update",
        "동일 invoice 갱신의 lock 순서 충돌",
        "deadlock graph와 transaction lock 순서 확인",
        "deadlock_count",
        "KC-DB-311",
        "deadlock graph에서 충돌 query를 확인하고 일관된 lock 순서와 재시도를 검증",
    ),
    IncidentCase(
        "queue",
        "notification-worker",
        "fp-queue-backlog",
        "notification queue backlog exceeded 50000",
        "NotificationDispatcher.dispatch",
        "외부 발송 지연으로 처리율 감소",
        "provider latency와 queue 처리율 비교",
        "queue_depth",
        "KC-QUEUE-087",
        "발송사 latency와 dequeue rate를 대조하고 실패 메시지 재처리 경로를 검증",
    ),
]


def _evidence(case: IncidentCase, *, with_similarity: bool) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "request_id": f"ab-{case.case_id}",
        "goal": f"{case.service} 장애 대응 권고 생성",
        "scope": {"systems": [case.service]},
        "selected_fingerprint": case.fingerprint,
        "core_logs": [case.message],
        "anomalies": [{"pattern": case.fingerprint, "message": case.message}],
        "clusters": [],
        "semantic_clusters": [],
        "stack_traces": [case.component],
        "incident_candidates": [{"root_cause_hint": case.cause_hint}],
        "risk_score": 82,
        "source_code_evidence": [{"symbol": case.component}],
        "known_pattern_matches": [],
        "similar_cases": [],
        "referenced_knowledge_card_ids": [],
    }
    if with_similarity:
        bundle["clusters"] = [
            {
                "cluster_id": f"pc-{case.case_id}",
                "representative_fingerprint": case.fingerprint,
                "pattern_similarity": 0.89,
            }
        ]
        bundle["semantic_clusters"] = [
            {
                "cluster_id": f"sc-{case.case_id}",
                "semantic_similarity": 0.87,
                "summary": case.cause_hint,
            }
        ]
        bundle["similar_cases"] = [
            {
                "card_id": case.card_id,
                "match_type": "semantic_similarity",
                "similarity": 0.88,
                "resolution_method": case.similar_resolution,
            }
        ]
        bundle["referenced_knowledge_card_ids"] = [case.card_id]
    return bundle


def _run_one(
    agent: RecommendationAgent,
    case: IncidentCase,
    *,
    with_similarity: bool,
) -> dict[str, Any]:
    evidence = _evidence(case, with_similarity=with_similarity)
    mcp = get_mcp_client()
    recommendation = agent._generate_candidate_once(
        mcp=mcp,
        impact_text=f"Risk Level: High; {case.service} 핵심 흐름 영향",
        metrics={case.metric: 82, "anomaly_score": 0.82},
        evidence_bundle=evidence,
        needs_data=False,
    )
    evaluation = agent._evaluate_recommendation(
        mcp=mcp,
        evidence_bundle=evidence,
        recommendation=recommendation,
    )
    evaluator_gap_count = len(evaluation.get("missing_points") or [])
    hard_fail_count = len(
        agent._hard_fail_reasons(
            evidence_bundle=evidence,
            recommendation=recommendation,
        )
    )
    evaluation = agent._apply_hard_fail_checks(
        evaluation=evaluation,
        evidence_bundle=evidence,
        recommendation=recommendation,
    )
    rendered = json.dumps(recommendation, ensure_ascii=False)
    card_cited = case.card_id in rendered if with_similarity else None
    return {
        "case_id": case.case_id,
        "condition": "similarity" if with_similarity else "baseline",
        "score": evaluation["score"],
        "passed": evaluation["passed"],
        "evaluator_gap_count": evaluator_gap_count,
        "hard_fail_count": hard_fail_count,
        "card_cited": card_cited,
        "rubric_scores": evaluation["rubric_scores"],
    }


def _summary(rows: list[dict[str, Any]], condition: str) -> dict[str, Any]:
    selected = [row for row in rows if row["condition"] == condition]
    scores = [int(row["score"]) for row in selected]
    return {
        "n": len(selected),
        "mean_score": round(statistics.mean(scores), 2),
        "median_score": round(statistics.median(scores), 2),
        "min_score": min(scores),
        "max_score": max(scores),
        "pass_rate_percent": round(
            100 * sum(bool(row["passed"]) for row in selected) / len(selected), 1
        ),
        "hard_fail_total": sum(int(row["hard_fail_count"]) for row in selected),
        "evaluator_gap_total": sum(
            int(row["evaluator_gap_count"]) for row in selected
        ),
    }


def main() -> None:
    if settings.llm_stub_mode:
        raise SystemExit(
            "LLM_STUB_MODE is enabled. Set LLM_STUB_MODE=false for this live benchmark."
        )

    base_url = os.getenv("OPENAI_BASE_URL") or None
    openai_client._client = lambda: OpenAI(
        base_url=base_url,
        timeout=45.0,
        max_retries=1,
    )

    agent = RecommendationAgent()
    jobs = [(case, condition) for case in CASES for condition in (False, True)]
    random.Random(20260719).shuffle(jobs)
    rows: list[dict[str, Any]] = []
    for index, (case, with_similarity) in enumerate(jobs, start=1):
        row = _run_one(agent, case, with_similarity=with_similarity)
        rows.append(row)
        print(
            f"[{index:02d}/{len(jobs)}] {row['case_id']} {row['condition']} "
            f"score={row['score']} passed={row['passed']}",
            flush=True,
        )

    baseline = _summary(rows, "baseline")
    similarity = _summary(rows, "similarity")
    baseline_mean = float(baseline["mean_score"])
    similarity_mean = float(similarity["mean_score"])
    cited = [row for row in rows if row["condition"] == "similarity"]
    result = {
        "model": settings.openai_model,
        "case_count": len(CASES),
        "baseline": baseline,
        "similarity": similarity,
        "absolute_improvement_points": round(similarity_mean - baseline_mean, 2),
        "relative_improvement_percent": round(
            100 * (similarity_mean - baseline_mean) / baseline_mean, 2
        ),
        "improvement_multiple": round(similarity_mean / baseline_mean, 3),
        "knowledge_card_citation_rate_percent": round(
            100 * sum(bool(row["card_cited"]) for row in cited) / len(cited), 1
        ),
        "paired_results": sorted(rows, key=lambda row: (row["case_id"], row["condition"])),
    }
    print("AB_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
