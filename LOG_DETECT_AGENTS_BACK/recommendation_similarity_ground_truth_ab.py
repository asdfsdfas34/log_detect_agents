"""Ground-truth A/B benchmark for recommendation similarity evidence.

Both conditions receive the same raw incident evidence. Only the similarity condition receives
pattern/semantic matches and a historical resolution. A blinded evaluator scores both outputs
against the same held-out expected cause and resolution.
"""

from __future__ import annotations

import json
import os
import random
import statistics
from typing import Any

from openai import OpenAI

from app.agents.recommendation import RecommendationAgent
from app.config import settings
from app.llm import openai_client
from app.mcp import get_mcp_client
from recommendation_similarity_ab import CASES, IncidentCase


def _evidence(case: IncidentCase, *, with_similarity: bool) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "request_id": f"gt-ab-{case.case_id}",
        "goal": f"{case.service} 장애 대응 권고 생성",
        "scope": {"systems": [case.service]},
        "selected_fingerprint": case.fingerprint,
        "core_logs": [case.message],
        "anomalies": [{"pattern": case.fingerprint, "message": case.message}],
        "clusters": [],
        "semantic_clusters": [],
        "stack_traces": [case.component],
        "incident_candidates": [],
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
                "pattern_similarity": 0.89,
                "representative_message": case.message,
            }
        ]
        bundle["semantic_clusters"] = [
            {
                "cluster_id": f"sc-{case.case_id}",
                "semantic_similarity": 0.87,
                "root_cause_summary": case.cause_hint,
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


def _evaluate_against_ground_truth(
    *,
    case: IncidentCase,
    recommendation: dict[str, Any],
) -> dict[str, Any]:
    schema = {
        "rubric_scores": {
            "cause_alignment": "integer 0-25",
            "resolution_alignment": "integer 0-30",
            "evidence_grounding": "integer 0-20",
            "verification_quality": "integer 0-15",
            "safety": "integer 0-10",
        },
        "feedback": "string",
    }
    ground_truth = {
        "service": case.service,
        "fingerprint": case.fingerprint,
        "observed_message": case.message,
        "component": case.component,
        "expected_cause": case.cause_hint,
        "expected_resolution": case.similar_resolution,
        "verification_metric": case.metric,
    }
    raw = get_mcp_client().call_tool(
        "openai.generate_text",
        {
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a blinded SRE benchmark evaluator. Score only alignment with "
                        "the held-out ground truth. Return one JSON object and no markdown."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "Score the recommendation using this 100-point rubric:\n"
                        "- Cause alignment with held-out expected cause: 25\n"
                        "- Action alignment with held-out expected resolution: 30\n"
                        "- Claims grounded in observed log, fingerprint, component, or cited "
                        "case: 20\n"
                        "- Concrete verification using the expected metric or an equivalent "
                        "observable check: 15\n"
                        "- Safe, non-destructive actions: 10\n"
                        "Do not infer which experimental condition produced the answer. "
                        "Score strictly and use integer scores within each maximum.\n"
                        f"Schema: {json.dumps(schema, ensure_ascii=False)}\n"
                        f"Held-out ground truth: {json.dumps(ground_truth, ensure_ascii=False)}\n"
                        f"Recommendation: {json.dumps(recommendation, ensure_ascii=False)}"
                    ),
                },
            ],
            "temperature": 0,
        },
    )
    payload = RecommendationAgent._load_json_object(str(raw or ""))
    maxima = {
        "cause_alignment": 25,
        "resolution_alignment": 30,
        "evidence_grounding": 20,
        "verification_quality": 15,
        "safety": 10,
    }
    raw_scores = payload.get("rubric_scores")
    if not isinstance(raw_scores, dict):
        raise ValueError("Ground-truth evaluation must include rubric_scores.")
    scores = {
        key: max(0, min(maximum, int(raw_scores.get(key, 0))))
        for key, maximum in maxima.items()
    }
    return {"score": sum(scores.values()), "rubric_scores": scores}


def _run_one(
    agent: RecommendationAgent,
    case: IncidentCase,
    *,
    with_similarity: bool,
) -> dict[str, Any]:
    evidence = _evidence(case, with_similarity=with_similarity)
    recommendation = agent._generate_candidate_once(
        mcp=get_mcp_client(),
        impact_text=f"Risk Level: High; {case.service} 핵심 흐름 영향",
        metrics={case.metric: 82, "anomaly_score": 0.82},
        evidence_bundle=evidence,
        needs_data=False,
        feedback=(
            "검증 단계는 로그·메트릭·테스트처럼 관찰 가능한 기준을 사용하고, 제공된 "
            "근거 범위를 넘는 원인 단정은 피하세요."
        ),
    )
    evaluation = _evaluate_against_ground_truth(case=case, recommendation=recommendation)
    rendered = json.dumps(recommendation, ensure_ascii=False)
    return {
        "case_id": case.case_id,
        "condition": "similarity" if with_similarity else "baseline",
        "score": evaluation["score"],
        "rubric_scores": evaluation["rubric_scores"],
        "passed": evaluation["score"] >= 80,
        "card_cited": case.card_id in rendered if with_similarity else None,
    }


def _summarize(rows: list[dict[str, Any]], condition: str) -> dict[str, Any]:
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
    }


def main() -> None:
    if settings.llm_stub_mode:
        raise SystemExit("Set LLM_STUB_MODE=false for this live benchmark.")
    base_url = os.getenv("OPENAI_BASE_URL") or None
    openai_client._client = lambda: OpenAI(
        base_url=base_url,
        timeout=45.0,
        max_retries=1,
    )

    jobs = [(case, condition) for case in CASES for condition in (False, True)]
    random.Random(20260719).shuffle(jobs)
    agent = RecommendationAgent()
    rows: list[dict[str, Any]] = []
    for index, (case, with_similarity) in enumerate(jobs, start=1):
        row = _run_one(agent, case, with_similarity=with_similarity)
        rows.append(row)
        print(
            f"[{index:02d}/{len(jobs)}] {row['case_id']} {row['condition']} "
            f"score={row['score']} passed={row['passed']}",
            flush=True,
        )

    baseline = _summarize(rows, "baseline")
    similarity = _summarize(rows, "similarity")
    baseline_mean = float(baseline["mean_score"])
    similarity_mean = float(similarity["mean_score"])
    similarity_rows = [row for row in rows if row["condition"] == "similarity"]
    paired = {
        case.case_id: {
            row["condition"]: row["score"]
            for row in rows
            if row["case_id"] == case.case_id
        }
        for case in CASES
    }
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
        "improved_case_count": sum(
            values["similarity"] > values["baseline"] for values in paired.values()
        ),
        "knowledge_card_citation_rate_percent": round(
            100
            * sum(bool(row["card_cited"]) for row in similarity_rows)
            / len(similarity_rows),
            1,
        ),
        "paired_scores": paired,
        "rows": sorted(rows, key=lambda row: (row["case_id"], row["condition"])),
    }
    print("GT_AB_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
