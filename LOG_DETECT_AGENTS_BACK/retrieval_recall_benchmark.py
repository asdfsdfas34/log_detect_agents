"""Live embedding benchmark for cross-fingerprint Knowledge Card retrieval.

The benchmark is read-only with respect to SQLite and ChromaDB. It embeds an in-memory corpus
of ten case cards, fifty positive variants, and fifty negative controls, then compares exact,
pattern, semantic, and hybrid retrieval.
"""

from __future__ import annotations

import json
import math
import os
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from app.db import chroma_store, scenario_store
from recommendation_similarity_ab import CASES, IncidentCase

SEMANTIC_THRESHOLD = 0.80
TOP_K_VALUES = (1, 3, 5)


@dataclass(frozen=True)
class QueryCase:
    query_id: str
    fingerprint: str
    service: str
    message: str
    expected_card_id: str | None


def _card_text(case: IncidentCase) -> str:
    return "\n".join(
        [
            f"service={case.service}",
            f"fingerprint={case.fingerprint}",
            "log_level=ERROR",
            f"message={case.message}",
            f"normalized_message={case.message}",
            f"stacktrace={case.component}",
            f"root_cause={case.cause_hint}",
            f"recommendation={case.action_hint}",
            f"resolution_method={case.similar_resolution}",
        ]
    )


def _positive_messages(case: IncidentCase) -> list[str]:
    return [
        f"{case.service}에서 {case.cause_hint} 징후와 요청 실패가 반복 관찰됨",
        f"{case.component} 구간 이상으로 {case.metric} 지표가 지속 상승함",
        f"기존 메시지와 표현은 다르지만 {case.action_hint} 검토가 필요한 장애 발생",
        f"{case.message}와 동일 계열의 오류가 다른 요청 경로에서 다시 발생함",
        f"운영 경보: {case.cause_hint} 가능성이 있어 {case.similar_resolution}",
    ]


def _negative_messages(case: IncidentCase) -> list[str]:
    return [
        f"정상 상태: {case.message} 관련 오류가 없고 모든 요청이 성공함",
        f"{case.component} 정상 동작, {case.metric} 값이 기준 범위 내에 있음",
        f"테스트 알림 종료: 과거 {case.cause_hint} 현상은 재발하지 않음",
        f"{case.service} 배포 완료 후 오류와 지연이 관찰되지 않음",
        f"{case.action_hint} 문서 검토만 수행했으며 현재 장애는 없음",
    ]


def _queries() -> tuple[list[QueryCase], list[QueryCase]]:
    positives: list[QueryCase] = []
    negatives: list[QueryCase] = []
    for case in CASES:
        for index, message in enumerate(_positive_messages(case), start=1):
            positives.append(
                QueryCase(
                    query_id=f"pos-{case.case_id}-{index}",
                    fingerprint=f"variant-{case.case_id}-{index}",
                    service=case.service,
                    message=message,
                    expected_card_id=case.card_id,
                )
            )
        for index, message in enumerate(_negative_messages(case), start=1):
            negatives.append(
                QueryCase(
                    query_id=f"neg-{case.case_id}-{index}",
                    fingerprint=f"normal-{case.case_id}-{index}",
                    service=case.service,
                    message=message,
                    expected_card_id=None,
                )
            )
    return positives, negatives


def _cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm <= 0 or right_norm <= 0:
        return 0.0
    return max(0.0, min(1.0, dot / (left_norm * right_norm)))


def _embed_all(texts: list[str]) -> list[list[float]]:
    if chroma_store._embedding_provider() != "openai":
        raise RuntimeError("This benchmark currently supports the configured OpenAI provider.")
    api_key = chroma_store._embedding_api_key()
    if not api_key:
        raise RuntimeError("Embedding API key is not configured.")
    base_url = (
        os.getenv("OPENAI_EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
    )
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=45.0, max_retries=1)
    dimensions = chroma_store._case_card_dimensions()
    batch_size = chroma_store._embedding_batch_size()
    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = client.embeddings.create(
            model=chroma_store._embedding_model(),
            input=batch,
            dimensions=dimensions,
        )
        vectors.extend(list(item.embedding) for item in response.data)
        print(
            f"embedded {min(start + len(batch), len(texts))}/{len(texts)} texts",
            flush=True,
        )
    if len(vectors) != len(texts):
        raise RuntimeError(f"embedding size mismatch: {len(vectors)} != {len(texts)}")
    return vectors


def _pattern_score(query: QueryCase, card: IncidentCase) -> float:
    return scenario_store._pattern_similarity(
        {
            "fingerprint": query.fingerprint,
            "service_name": query.service,
            "log_level": "ERROR",
            "message": query.message,
        },
        {
            "similarity": 0.0,
            "document": card.message,
            "metadata": {
                "fingerprint": card.fingerprint,
                "service_name": card.service,
                "log_level": "ERROR",
                "normalized_message": card.message,
                "stacktrace": card.component,
            },
        },
    )


def _exact_score(query: QueryCase, card: IncidentCase) -> float:
    return 1.0 if query.fingerprint == card.fingerprint else 0.0


def _evaluate_method(
    *,
    method: str,
    positives: list[QueryCase],
    negatives: list[QueryCase],
    score_for: Callable[[QueryCase, IncidentCase], float],
    accepted: Callable[[float, float], bool],
) -> dict[str, Any]:
    positive_rankings: list[list[tuple[str, float]]] = []
    reciprocal_ranks: list[float] = []
    threshold_hits = 0
    positive_top_scores: list[float] = []
    for query in positives:
        ranking = sorted(
            ((card.card_id, score_for(query, card)) for card in CASES),
            key=lambda item: item[1],
            reverse=True,
        )
        positive_rankings.append(ranking)
        positive_top_scores.append(ranking[0][1])
        expected_rank = next(
            index
            for index, (card_id, _score) in enumerate(ranking, start=1)
            if card_id == query.expected_card_id
        )
        reciprocal_ranks.append(1.0 / expected_rank)
        expected_score = next(
            score for card_id, score in ranking if card_id == query.expected_card_id
        )
        top_score = ranking[0][1]
        if ranking[0][0] == query.expected_card_id and accepted(expected_score, top_score):
            threshold_hits += 1

    negative_false_positives = 0
    negative_top_scores: list[float] = []
    for query in negatives:
        ranking = sorted(
            ((card.card_id, score_for(query, card)) for card in CASES),
            key=lambda item: item[1],
            reverse=True,
        )
        top_score = ranking[0][1]
        negative_top_scores.append(top_score)
        if accepted(top_score, top_score):
            negative_false_positives += 1

    recalls = {
        f"recall_at_{k}_percent": round(
            100
            * sum(
                query.expected_card_id in {card_id for card_id, _score in ranking[:k]}
                for query, ranking in zip(positives, positive_rankings, strict=True)
            )
            / len(positives),
            1,
        )
        for k in TOP_K_VALUES
    }
    if method == "exact_fingerprint":
        recalls = {key: 0.0 for key in recalls}
        reciprocal_ranks = [0.0 for _ in reciprocal_ranks]
    return {
        "method": method,
        **recalls,
        "mrr": round(statistics.mean(reciprocal_ranks), 3),
        "threshold_top1_recall_percent": round(100 * threshold_hits / len(positives), 1),
        "negative_false_positive_rate_percent": round(
            100 * negative_false_positives / len(negatives), 1
        ),
        "positive_top_score_mean": round(statistics.mean(positive_top_scores), 4),
        "negative_top_score_mean": round(statistics.mean(negative_top_scores), 4),
    }


def _variant_index(query: QueryCase) -> int:
    return int(query.query_id.rsplit("-", 1)[-1])


def _top_result(
    query: QueryCase,
    score_for: Callable[[QueryCase, IncidentCase], float],
) -> tuple[str, float]:
    return max(
        ((card.card_id, score_for(query, card)) for card in CASES),
        key=lambda item: item[1],
    )


def _calibrate_threshold(
    *,
    positives: list[QueryCase],
    negatives: list[QueryCase],
    score_for: Callable[[QueryCase, IncidentCase], float],
) -> dict[str, Any]:
    validation_positives = [query for query in positives if _variant_index(query) <= 3]
    test_positives = [query for query in positives if _variant_index(query) > 3]
    validation_negatives = [query for query in negatives if _variant_index(query) <= 3]
    test_negatives = [query for query in negatives if _variant_index(query) > 3]

    validation_positive_results = [
        (query, *_top_result(query, score_for)) for query in validation_positives
    ]
    validation_negative_results = [
        _top_result(query, score_for) for query in validation_negatives
    ]
    thresholds = sorted(
        {
            0.0,
            1.0,
            *[score for _query, _card_id, score in validation_positive_results],
            *[score for _card_id, score in validation_negative_results],
        }
    )

    candidates: list[tuple[float, float, float, float]] = []
    for threshold in thresholds:
        recall = sum(
            card_id == query.expected_card_id and score >= threshold
            for query, card_id, score in validation_positive_results
        ) / len(validation_positive_results)
        false_positive_rate = sum(
            score >= threshold for _card_id, score in validation_negative_results
        ) / len(validation_negative_results)
        candidates.append((recall - false_positive_rate, recall, -false_positive_rate, threshold))
    constrained_candidates = [candidate for candidate in candidates if -candidate[2] <= 0.10]
    if not constrained_candidates:
        constrained_candidates = candidates
    _youden, validation_recall, negative_fpr, threshold = max(
        constrained_candidates,
        key=lambda candidate: (candidate[1], candidate[0], candidate[3]),
    )
    validation_fpr = -negative_fpr

    test_positive_results = [
        (query, *_top_result(query, score_for)) for query in test_positives
    ]
    test_negative_results = [_top_result(query, score_for) for query in test_negatives]
    test_recall = sum(
        card_id == query.expected_card_id and score >= threshold
        for query, card_id, score in test_positive_results
    ) / len(test_positive_results)
    test_fpr = sum(score >= threshold for _card_id, score in test_negative_results) / len(
        test_negative_results
    )
    return {
        "selection": "maximum validation recall with false-positive rate <= 10%",
        "validation_positive_count": len(validation_positives),
        "validation_negative_count": len(validation_negatives),
        "test_positive_count": len(test_positives),
        "test_negative_count": len(test_negatives),
        "selected_threshold": round(threshold, 4),
        "validation_recall_percent": round(validation_recall * 100, 1),
        "validation_false_positive_rate_percent": round(validation_fpr * 100, 1),
        "test_recall_percent": round(test_recall * 100, 1),
        "test_miss_rate_percent": round((1 - test_recall) * 100, 1),
        "test_false_positive_rate_percent": round(test_fpr * 100, 1),
    }


def main() -> None:
    positives, negatives = _queries()
    texts = [
        *[_card_text(case) for case in CASES],
        *[query.message for query in positives],
        *[query.message for query in negatives],
    ]
    embeddings = _embed_all(texts)
    card_vectors = embeddings[: len(CASES)]
    positive_offset = len(CASES)
    negative_offset = positive_offset + len(positives)
    query_vectors = {
        **{
            query.query_id: embeddings[positive_offset + index]
            for index, query in enumerate(positives)
        },
        **{
            query.query_id: embeddings[negative_offset + index]
            for index, query in enumerate(negatives)
        },
    }
    card_vector_by_id = {
        case.card_id: card_vectors[index] for index, case in enumerate(CASES)
    }

    def semantic_score(query: QueryCase, card: IncidentCase) -> float:
        return _cosine(query_vectors[query.query_id], card_vector_by_id[card.card_id])

    def hybrid_score(query: QueryCase, card: IncidentCase) -> float:
        return scenario_store._hybrid_cluster_score(
            _pattern_score(query, card), semantic_score(query, card)
        )

    results = [
        _evaluate_method(
            method="exact_fingerprint",
            positives=positives,
            negatives=negatives,
            score_for=_exact_score,
            accepted=lambda score, _top: score >= 1.0,
        ),
        _evaluate_method(
            method="pattern_similarity",
            positives=positives,
            negatives=negatives,
            score_for=_pattern_score,
            accepted=lambda score, _top: score
            >= scenario_store.PATTERN_CLUSTER_MEMBER_THRESHOLD,
        ),
        _evaluate_method(
            method="semantic_similarity",
            positives=positives,
            negatives=negatives,
            score_for=semantic_score,
            accepted=lambda score, _top: score >= SEMANTIC_THRESHOLD,
        ),
        _evaluate_method(
            method="pattern_semantic_hybrid",
            positives=positives,
            negatives=negatives,
            score_for=hybrid_score,
            accepted=lambda score, _top: score
            >= scenario_store.PATTERN_CLUSTER_HYBRID_PATTERN_THRESHOLD,
        ),
    ]
    calibrated = {
        "pattern_similarity": _calibrate_threshold(
            positives=positives,
            negatives=negatives,
            score_for=_pattern_score,
        ),
        "semantic_similarity": _calibrate_threshold(
            positives=positives,
            negatives=negatives,
            score_for=semantic_score,
        ),
        "pattern_semantic_hybrid": _calibrate_threshold(
            positives=positives,
            negatives=negatives,
            score_for=hybrid_score,
        ),
    }
    output = {
        "embedding_provider": chroma_store._embedding_provider(),
        "embedding_model": chroma_store._embedding_model(),
        "positive_count": len(positives),
        "negative_count": len(negatives),
        "semantic_threshold": SEMANTIC_THRESHOLD,
        "results": results,
        "calibrated_threshold_test": calibrated,
    }
    print("RETRIEVAL_RESULT=" + json.dumps(output, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
