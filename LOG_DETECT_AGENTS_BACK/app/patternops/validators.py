"""PatternOps skill validator dispatch."""

from __future__ import annotations

from typing import Any


def validate_skill_result(
    *, skill_id: str, state: dict[str, Any], validators: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Run lightweight validators for a skill execution."""

    checks = [
        str(item.get("validator_type", ""))
        for item in validators
        if isinstance(item, dict)
    ]
    results = []
    for validator_type in checks:
        passed, message = _run_validator(
            skill_id=skill_id,
            validator_type=validator_type,
            state=state,
        )
        results.append(
            {
                "skill_id": skill_id,
                "validator_type": validator_type,
                "passed": passed,
                "message": message,
            }
        )
    return results


def _run_validator(
    *, skill_id: str, validator_type: str, state: dict[str, Any]
) -> tuple[bool, str]:
    evidence = state.get("evidence", {})
    final = state.get("final", {}) or {}
    if validator_type in {
        "non_empty_or_fallback_logs",
        "service_scope_match",
    }:
        return bool(evidence.get("normalized_logs")), "normalized_logs present"
    if validator_type in {"regex_compile", "sample_before_after"}:
        logs = evidence.get("normalized_logs") or []
        return all("message_template" in item for item in logs), "message templates present"
    if validator_type in {"stable_fingerprint", "occurrence_count_preserved"}:
        logs = evidence.get("normalized_logs") or []
        return all("fingerprint" in item for item in logs), "fingerprints present"
    if validator_type in {"confidence_threshold", "match_source_present"}:
        return bool(
            evidence.get("known_pattern_matches")
            or evidence.get("new_pattern_candidates")
            or evidence.get("pattern_ops_matches")
            or evidence.get("clusters")
        ), "pattern match artifacts present"
    if validator_type in {"baseline_comparison", "severity_reason"}:
        return "anomalies" in evidence, "anomaly artifact key present"
    if validator_type in {"fingerprint_match", "confidence_present"}:
        cards = evidence.get("related_knowledge_cards") or state.get("rag", {}).get(
            "related_knowledge", []
        )
        if not cards:
            return True, "no related knowledge cards required"
        if validator_type == "fingerprint_match":
            return any(
                _has_any_text(item, ("card_id", "fingerprint", "resolution_method"))
                for item in cards
                if isinstance(item, dict)
            ), "related knowledge card identity present"
        return any(
            _has_any_text(item, ("confidence", "score", "similarity", "card_id"))
            for item in cards
            if isinstance(item, dict)
        ), "related knowledge confidence or identity present"
    if validator_type in {"evidence_linked_actions", "owner_present"}:
        candidate = evidence.get("recommendation_candidate")
        actions = []
        if isinstance(candidate, dict):
            actions = candidate.get("recommended_actions") or []
        if not actions:
            actions = final.get("recommended_actions") or []
        if validator_type == "owner_present":
            return _actions_have_required_text(actions, ("owner",)), "owners present"
        return _actions_have_required_text(
            actions, ("action", "reason")
        ), "evidence-linked actions present"
    if validator_type in {"minimum_quality_score", "hard_fail_checks"}:
        bundle = final.get("evidence_bundle") or evidence.get(
            "recommendation_evidence_bundle", {}
        )
        status = str(bundle.get("quality_gate_status") or "").lower()
        if status == "fallback":
            return True, "fallback recommendation recorded"
        if validator_type == "minimum_quality_score":
            score = bundle.get("quality_score")
            return _numeric_score(score) >= 80, "quality score meets threshold"
        return bool(final.get("recommended_actions")) and status in {
            "passed",
            "best_effort",
        }, "quality gate completed"
    return True, f"{validator_type or skill_id} validator recorded"


def _has_any_text(item: dict[str, Any], keys: tuple[str, ...]) -> bool:
    return any(str(item.get(key) or "").strip() for key in keys)


def _actions_have_required_text(actions: Any, keys: tuple[str, ...]) -> bool:
    if not isinstance(actions, list) or not actions:
        return False
    return all(
        isinstance(action, dict)
        and all(str(action.get(key) or "").strip() for key in keys)
        for action in actions
    )


def _numeric_score(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
