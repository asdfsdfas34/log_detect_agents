"""RecommendationAgent implementation using MCP tools."""

from __future__ import annotations

import json
import re
from typing import Any

from app.mcp import get_mcp_client
from app.patternops.runner import pattern_skill_runner
from app.state import SharedState

_REQUIRED_ACTION_KEYS = {"priority", "action", "owner"}
_MAX_QUALITY_ATTEMPTS = 3
_MIN_QUALITY_SCORE = 80


class RecommendationAgent:
    """Build actionable remediation outputs with an LLM quality gate."""

    name = "RecommendationAgent"

    def run(self, state: SharedState) -> SharedState:
        return pattern_skill_runner.run_for_agent(
            state,
            agent_name=self.name,
            scope="recommendation",
            operations={"recommendation_generation": self._generate_recommendation},
        )

    def _generate_recommendation(self, state: SharedState) -> SharedState:
        risk = state["assessment"]["risk_score"] or 0
        anomalies = state["evidence"]["anomalies"]
        impact_text = "\n".join(state["assessment"]["rationale"])
        metrics = state["metrics"]
        source_evidence = state["evidence"].get("source_code_evidence", [])
        known_matches = state["evidence"].get("known_pattern_matches", [])
        pattern_ops_matches = state["evidence"].get("pattern_ops_matches", [])
        pattern_ops_contracts = state["evidence"].get("pattern_ops_contracts", [])
        pattern_ops_skill_plan = state["evidence"].get("pattern_ops_skill_plan", {})
        pattern_ops_skill_executions = state["evidence"].get(
            "pattern_ops_skill_executions", []
        )
        related = state.get("rag", {}).get("related_knowledge", [])

        needs_data = any(
            "additional data" in str(item).lower() or "추가" in str(item)
            for item in state["decisions"]["assumptions"]
        )

        evidence_bundle = {
            "request_id": state.get("request_id"),
            "goal": state.get("goal"),
            "scope": state.get("scope", {}),
            "selected_fingerprint": state.get("scope", {})
            .get("filters", {})
            .get("fingerprint"),
            "core_logs": [item.get("message") for item in anomalies[:5]],
            "anomalies": anomalies[:5],
            "clusters": state["evidence"].get("clusters", [])[:5],
            "stack_traces": state["evidence"].get("stack_traces", [])[:3],
            "normalized_logs": state["evidence"].get("normalized_logs", [])[:10],
            "incident_candidates": state["evidence"].get("incident_candidates", [])[:5],
            "anomaly_score": state["metrics"].get("anomaly_score"),
            "risk_score": risk,
            "source_code_evidence": source_evidence[:5],
            "known_pattern_matches": known_matches[:5],
            "pattern_ops_matches": pattern_ops_matches[:5],
            "pattern_ops_contracts": pattern_ops_contracts[:10],
            "pattern_ops_skill_plan": pattern_ops_skill_plan,
            "pattern_ops_skill_executions": pattern_ops_skill_executions,
            "known_pattern_summary": {
                "total_matches": len(known_matches),
                "suppressed": len(state["evidence"].get("suppressed_logs", [])),
            },
            "pattern_ops_summary": {
                "matched_contracts": len(pattern_ops_matches),
                "loaded_contracts": len(pattern_ops_contracts),
            },
            "summary": state["evidence"].get("summary", {}),
            "recommendation": state["evidence"].get("recommendation", {}),
            "similar_cases": related,
        }

        mcp = get_mcp_client()
        try:
            recommendation = self._generate_with_quality_gate(
                mcp=mcp,
                impact_text=impact_text,
                metrics=metrics,
                evidence_bundle=evidence_bundle,
                needs_data=needs_data,
            )
        except Exception as exc:  # noqa: BLE001
            recommendation = self._fallback_recommendation(
                risk=risk, anomalies=anomalies, needs_data=needs_data
            )
            state["decisions"]["assumptions"].append(
                f"LLM/RAG recommendation failed, fallback used: {exc}"
            )

        evidence_bundle["recommendation_source"] = recommendation["source"]
        evidence_bundle["quality_score"] = recommendation.get("quality_score")
        evidence_bundle["quality_gate_status"] = recommendation.get(
            "quality_gate_status"
        )
        evidence_bundle["quality_attempts"] = recommendation.get("quality_attempts")
        evidence_bundle["quality_feedback"] = recommendation.get("quality_feedback")
        if recommendation.get("prevention_steps"):
            evidence_bundle["prevention_steps"] = recommendation["prevention_steps"]

        state["final"] = {
            "executive_summary": recommendation["executive_summary"],
            "recommended_actions": recommendation["recommended_actions"],
            "verification_steps": recommendation["verification_steps"],
            "additional_data_needed": recommendation["additional_data_needed"],
            "generated_answer": self._render_generated_answer(recommendation),
            "evidence_bundle": evidence_bundle,
            "saved_recommendation_id": None,
        }

        state["decisions"]["agents_run"].append(self.name)
        return state

    def _generate_with_quality_gate(
        self,
        *,
        mcp: Any,
        impact_text: str,
        metrics: dict[str, Any],
        evidence_bundle: dict[str, Any],
        needs_data: bool,
    ) -> dict[str, Any]:
        best: dict[str, Any] | None = None
        feedback: str | None = None
        last_error: Exception | None = None

        for attempt in range(1, _MAX_QUALITY_ATTEMPTS + 1):
            try:
                raw_response = mcp.call_tool(
                    "openai.generate_text",
                    {
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are an SRE Recommendation Agent. Return "
                                    "exactly one JSON object and no markdown. "
                                    "All user-facing JSON string values must be written in Korean."
                                ),
                            },
                            {
                                "role": "user",
                                "content": self._build_structured_prompt(
                                    impact_text=impact_text,
                                    metrics=metrics,
                                    evidence_bundle=evidence_bundle,
                                    needs_data=needs_data,
                                    feedback=feedback,
                                ),
                            },
                        ],
                        "temperature": 0.2,
                    },
                )
                recommendation = self._parse_structured_recommendation(raw_response)
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                feedback = (
                    "The previous answer was invalid. Regenerate valid JSON that "
                    "matches the schema and contains concrete, evidence-linked actions."
                )
                continue

            evaluation = self._evaluate_recommendation(
                mcp=mcp,
                evidence_bundle=evidence_bundle,
                recommendation=recommendation,
            )
            evaluation = self._apply_hard_fail_checks(
                evaluation=evaluation,
                evidence_bundle=evidence_bundle,
                recommendation=recommendation,
            )
            recommendation["quality_score"] = evaluation["score"]
            recommendation["quality_gate_status"] = (
                "passed" if evaluation["passed"] else "needs_improvement"
            )
            recommendation["quality_attempts"] = attempt
            recommendation["quality_feedback"] = evaluation["feedback"]

            if best is None or evaluation["score"] > int(best["quality_score"] or 0):
                best = recommendation

            if evaluation["passed"]:
                return recommendation

            feedback = evaluation["feedback"]

        if best is not None:
            best["quality_gate_status"] = "best_effort"
            return best
        if last_error is not None:
            raise last_error
        raise ValueError("Recommendation quality loop did not produce a candidate.")

    def _evaluate_recommendation(
        self,
        *,
        mcp: Any,
        evidence_bundle: dict[str, Any],
        recommendation: dict[str, Any],
    ) -> dict[str, Any]:
        raw_response = mcp.call_tool(
            "openai.generate_text",
            {
                "messages": [
                    {
                            "role": "system",
                            "content": (
                                "You are a strict SRE recommendation quality evaluator. "
                                "Return exactly one JSON object and no markdown. "
                                "All feedback and user-facing string values must be written in Korean."
                            ),
                        },
                    {
                        "role": "user",
                        "content": self._build_quality_eval_prompt(
                            evidence_bundle=evidence_bundle,
                            recommendation=recommendation,
                        ),
                    },
                ],
                "temperature": 0,
            },
        )
        return self._parse_quality_evaluation(raw_response)

    @staticmethod
    def _build_structured_prompt(
        *,
        impact_text: str,
        metrics: dict[str, Any],
        evidence_bundle: dict[str, Any],
        needs_data: bool,
        feedback: str | None = None,
    ) -> str:
        schema = {
            "executive_summary": "string: Korean summary",
            "root_cause_analysis": "string: Korean evidence-backed cause analysis",
            "impact_analysis": "string: Korean service impact and risk explanation",
            "recommended_actions": [
                {
                    "priority": "P1|P2|P3",
                    "action": "string: Korean concrete remediation action",
                    "reason": "string: Korean reason why this action is recommended",
                    "target": "string: file, component, endpoint, or runtime area",
                    "owner": "backend|sre|service-owner|data|security",
                    "expected_effect": "string: Korean expected effect",
                    "risk": "string: Korean rollout or validation risk",
                    "evidence": ["string"],
                }
            ],
            "verification_steps": ["string: Korean verification step"],
            "prevention_steps": ["string: Korean prevention step"],
            "additional_data_needed": ["string: Korean missing data"],
            "confidence": "low|mid|high",
        }
        feedback_text = (
            f"\nPrevious quality feedback to fix:\n{feedback}\n" if feedback else ""
        )
        return (
            "Create a high-quality incident remediation recommendation from the "
            "evidence bundle and similar cases.\n"
            "Rules:\n"
            "- Return exactly one JSON object compatible with the schema below.\n"
            "- Keep JSON field names exactly as specified, but write every user-facing "
            "string value in Korean.\n"
            "- Do not include markdown, prose outside JSON, or code blocks.\n"
            "- recommended_actions and verification_steps must not be empty.\n"
            "- Tie root cause, actions, verification, and prevention to concrete "
            "evidence: fingerprint, message, stack trace, risk, source code, "
            "known patterns, and similar case resolution methods.\n"
            "- Do not propose infrastructure changes, arbitrary DB schema changes, "
            "secret rotation, credential rotation, destructive commands, or "
            "unverified operational actions.\n"
            "- If evidence is insufficient, state the gap in additional_data_needed "
            "instead of guessing.\n"
            "- Actions must be specific enough for an engineer to execute and verify.\n"
            f"{feedback_text}\n"
            f"Additional data needed flag: {needs_data}\n"
            f"JSON schema: {json.dumps(schema, ensure_ascii=False)}\n"
            f"Impact rationale: {impact_text}\n"
            f"Metrics: {json.dumps(metrics, ensure_ascii=False)}\n"
            f"Evidence bundle: {json.dumps(evidence_bundle, ensure_ascii=False)}"
        )

    @staticmethod
    def _build_quality_eval_prompt(
        *, evidence_bundle: dict[str, Any], recommendation: dict[str, Any]
    ) -> str:
        schema = {
            "rubric_scores": {
                "root_cause": "integer 0-25",
                "actionability": "integer 0-25",
                "verification": "integer 0-20",
                "prevention": "integer 0-15",
                "safety": "integer 0-15",
            },
            "passed": "boolean",
            "missing_points": ["string"],
            "weak_points": ["string"],
            "feedback": "string: Korean concrete instructions for regeneration",
        }
        return (
            "Evaluate the recommendation using this 100-point rubric:\n"
            "- Evidence-linked root cause analysis: 25\n"
            "- Concrete, executable remediation actions: 25\n"
            "- Verifiable validation steps using logs, metrics, APIs, or tests: 20\n"
            "- Prevention steps across code, operations, or monitoring: 15\n"
            "- No prohibited suggestions: 15\n\n"
            "Prohibited suggestions:\n"
            "- Infrastructure changes\n"
            "- Arbitrary DB schema changes\n"
            "- Secret or credential rotation\n"
            "- Destructive operational commands\n"
            "- Unsupported guesses not grounded in evidence\n\n"
            "Return rubric_scores for each item. Do not return a top-level score; "
            "the application will compute the total score by summing rubric_scores.\n"
            "Set passed=true only when the recommendation satisfies every hard fail "
            f"condition and your rubric total is at least {_MIN_QUALITY_SCORE}.\n"
            "Hard fail conditions:\n"
            "- root_cause_analysis does not cite concrete evidence from the bundle.\n"
            "- any recommended action is missing reason, target, expected_effect, or risk.\n"
            "- verification_steps has fewer than 2 concrete checks.\n"
            "- prevention_steps is empty.\n"
            "- the recommendation includes prohibited suggestions.\n"
            "Keep JSON field names exactly as specified, but write every user-facing "
            "string value in Korean.\n"
            f"Return JSON schema: {json.dumps(schema, ensure_ascii=False)}\n"
            f"Evidence bundle: {json.dumps(evidence_bundle, ensure_ascii=False)}\n"
            f"Recommendation: {json.dumps(recommendation, ensure_ascii=False)}"
        )

    def _parse_structured_recommendation(self, raw_response: Any) -> dict[str, Any]:
        payload = self._load_json_object(str(raw_response or ""))
        executive_summary = self._required_text(payload, "executive_summary")
        root_cause_analysis = self._required_text(payload, "root_cause_analysis")
        impact_analysis = self._required_text(payload, "impact_analysis")
        recommended_actions = self._validate_actions(payload.get("recommended_actions"))
        verification_steps = self._validate_text_list(
            payload.get("verification_steps"), "verification_steps"
        )
        prevention_steps = self._validate_text_list(
            payload.get("prevention_steps", []), "prevention_steps", required=False
        )
        additional_data_needed = self._validate_text_list(
            payload.get("additional_data_needed", []),
            "additional_data_needed",
            required=False,
        )
        confidence = str(payload.get("confidence") or "mid").lower()
        if confidence not in {"low", "mid", "high"}:
            confidence = "mid"
        return {
            "executive_summary": executive_summary,
            "root_cause_analysis": root_cause_analysis,
            "impact_analysis": impact_analysis,
            "recommended_actions": recommended_actions,
            "verification_steps": verification_steps,
            "prevention_steps": prevention_steps,
            "additional_data_needed": additional_data_needed or None,
            "confidence": confidence,
            "source": "llm_rag",
        }

    def _parse_quality_evaluation(self, raw_response: Any) -> dict[str, Any]:
        payload = self._load_json_object(str(raw_response or ""))
        rubric_scores = self._parse_rubric_scores(payload.get("rubric_scores"))
        score = sum(rubric_scores.values())
        missing_points = self._validate_text_list(
            payload.get("missing_points", []), "missing_points", required=False
        )
        weak_points = self._validate_text_list(
            payload.get("weak_points", []), "weak_points", required=False
        )
        feedback = str(payload.get("feedback") or "").strip()
        if not feedback:
            feedback = "; ".join(missing_points + weak_points) or (
                "근거 연결성, 조치의 구체성, 검증 방법, 재발 방지책을 보강하세요."
            )
        return {
            "score": score,
            "passed": bool(payload.get("passed")) and score >= _MIN_QUALITY_SCORE,
            "rubric_scores": rubric_scores,
            "missing_points": missing_points,
            "weak_points": weak_points,
            "feedback": feedback,
        }

    def _apply_hard_fail_checks(
        self,
        *,
        evaluation: dict[str, Any],
        evidence_bundle: dict[str, Any],
        recommendation: dict[str, Any],
    ) -> dict[str, Any]:
        failures = self._hard_fail_reasons(
            evidence_bundle=evidence_bundle,
            recommendation=recommendation,
        )
        if not failures:
            return evaluation

        existing_missing = list(evaluation.get("missing_points") or [])
        existing_feedback = str(evaluation.get("feedback") or "")
        evaluation["passed"] = False
        evaluation["missing_points"] = existing_missing + failures
        evaluation["feedback"] = " ".join(
            item
            for item in [
                existing_feedback,
                "하드 실패 조건을 해결하세요:",
                "; ".join(failures),
            ]
            if item
        )
        return evaluation

    @staticmethod
    def _hard_fail_reasons(
        *, evidence_bundle: dict[str, Any], recommendation: dict[str, Any]
    ) -> list[str]:
        failures: list[str] = []
        evidence_terms = [
            str(evidence_bundle.get("selected_fingerprint") or ""),
            *[
                str(item.get("pattern") or "")
                for item in evidence_bundle.get("anomalies", [])
                if isinstance(item, dict)
            ],
            *[
                str(item.get("message") or "")
                for item in evidence_bundle.get("anomalies", [])
                if isinstance(item, dict)
            ],
            *[str(item) for item in evidence_bundle.get("stack_traces", [])],
        ]
        evidence_terms = [term for term in evidence_terms if len(term.strip()) >= 4]
        root_cause = str(recommendation.get("root_cause_analysis") or "")
        if evidence_terms and not any(term in root_cause for term in evidence_terms):
            failures.append("원인 분석에 fingerprint/message/stack trace 등 구체 근거가 없습니다.")

        actions = recommendation.get("recommended_actions") or []
        for index, action in enumerate(actions, start=1):
            if not isinstance(action, dict):
                failures.append(f"{index}번 권장 조치 형식이 올바르지 않습니다.")
                continue
            missing = [
                key
                for key in ("reason", "target", "expected_effect", "risk")
                if not str(action.get(key) or "").strip()
            ]
            if missing:
                failures.append(f"{index}번 권장 조치에 필수 상세 필드가 없습니다: {missing}")

        if len(recommendation.get("verification_steps") or []) < 2:
            failures.append("검증 방법이 2개 미만입니다.")
        if not recommendation.get("prevention_steps"):
            failures.append("재발 방지책이 비어 있습니다.")

        prohibited_terms = ("인프라 변경", "DB 스키마 변경", "시크릿", "인증정보 회전", "파괴적")
        rendered = json.dumps(recommendation, ensure_ascii=False)
        if any(term in rendered for term in prohibited_terms):
            failures.append("금지된 운영/스키마/시크릿 관련 제안이 포함되어 있습니다.")
        return failures

    @staticmethod
    def _parse_rubric_scores(value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            raise ValueError("Quality evaluation must include rubric_scores.")
        max_scores = {
            "root_cause": 25,
            "actionability": 25,
            "verification": 20,
            "prevention": 15,
            "safety": 15,
        }
        scores: dict[str, int] = {}
        for key, max_score in max_scores.items():
            try:
                raw_score = int(value.get(key))
            except (TypeError, ValueError) as exc:
                raise ValueError(f"rubric_scores.{key} must be an integer.") from exc
            scores[key] = max(0, min(max_score, raw_score))
        return scores

    @staticmethod
    def _load_json_object(raw_response: str) -> dict[str, Any]:
        text = raw_response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
            text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            start = text.find("{")
            end = text.rfind("}")
            if start < 0 or end <= start:
                raise ValueError("Could not find a JSON object in the LLM response.") from exc
            parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("LLM response JSON must be an object.")
        return parsed

    @staticmethod
    def _required_text(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Required text field missing: {key}")
        return value.strip()

    @staticmethod
    def _validate_actions(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not value:
            raise ValueError("recommended_actions must be a non-empty list.")
        actions: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("recommended_actions items must be objects.")
            missing = [
                key
                for key in _REQUIRED_ACTION_KEYS
                if not isinstance(item.get(key), str) or not item.get(key, "").strip()
            ]
            if missing:
                raise ValueError(f"recommended_actions missing required fields: {missing}")
            action = {
                "priority": item["priority"].strip(),
                "action": item["action"].strip(),
                "owner": item["owner"].strip(),
            }
            for optional_key in ("reason", "target", "expected_effect", "risk"):
                optional_value = item.get(optional_key)
                if isinstance(optional_value, str) and optional_value.strip():
                    action[optional_key] = optional_value.strip()
            evidence = item.get("evidence")
            if isinstance(evidence, list):
                action["evidence"] = [
                    str(entry).strip() for entry in evidence if str(entry).strip()
                ]
            actions.append(action)
        return actions

    @staticmethod
    def _validate_text_list(
        value: Any, field_name: str, *, required: bool = True
    ) -> list[str]:
        if value in (None, "") and not required:
            return []
        if not isinstance(value, list):
            raise ValueError(f"{field_name} must be a list.")
        items = [str(item).strip() for item in value if str(item).strip()]
        if required and not items:
            raise ValueError(f"{field_name} must not be empty.")
        return items

    @staticmethod
    def _fallback_recommendation(
        *, risk: int, anomalies: list[dict], needs_data: bool
    ) -> dict[str, Any]:
        additional_data = (
            ["stack trace sample", "failed request payload", "recent deployment changes"]
            if needs_data
            else None
        )
        return {
            "executive_summary": (
                f"이상 패턴 {len(anomalies)}건이 탐지되었고 위험도는 {risk}/100입니다."
            ),
            "root_cause_analysis": (
                "LLM 추천 생성에 실패하여 이상 패턴 수와 위험도 점수를 기준으로 "
                "기본 분석을 제공합니다."
            ),
            "impact_analysis": f"현재 위험도 점수는 {risk}/100입니다.",
            "recommended_actions": [
                {
                    "priority": "P1" if risk >= 70 else "P2",
                    "action": (
                        "대표 오류 시나리오를 재현하고 코드 변경 전 stack trace의 "
                        "애플리케이션 프레임을 확인하세요."
                    ),
                    "owner": "backend",
                },
                {
                    "priority": "P2",
                    "action": (
                        "회귀 테스트를 추가하고 배포 후 동일 fingerprint 재발 여부를 "
                        "모니터링하세요."
                    ),
                    "owner": "sre",
                },
            ],
            "verification_steps": [
                "수정 후 동일 fingerprint 발생 건수가 감소했는지 확인합니다.",
                "수정 전후 latency_p95, error_rate, request volume을 비교합니다.",
                "동일 normalized message가 애플리케이션 로그에 재발하는지 확인합니다.",
            ],
            "prevention_steps": [],
            "additional_data_needed": additional_data,
            "confidence": "mid",
            "source": "fallback",
            "quality_score": None,
            "quality_gate_status": "fallback",
            "quality_attempts": 0,
            "quality_feedback": None,
        }

    @staticmethod
    def _render_generated_answer(recommendation: dict[str, Any]) -> str:
        lines = [
            "요약",
            f"- {recommendation['executive_summary']}",
            "",
            "원인 분석",
            f"- {recommendation.get('root_cause_analysis') or '-'}",
            "",
            "영향 분석",
            f"- {recommendation.get('impact_analysis') or '-'}",
            "",
            "권장 조치",
        ]
        for item in recommendation["recommended_actions"]:
            lines.append(f"- [{item['priority']}] {item['action']} (owner: {item['owner']})")
            for label, key in (
                ("근거", "reason"),
                ("대상", "target"),
                ("기대 효과", "expected_effect"),
                ("주의점", "risk"),
            ):
                if item.get(key):
                    lines.append(f"  - {label}: {item[key]}")
        lines.extend(["", "검증 방법"])
        lines.extend(f"- {item}" for item in recommendation["verification_steps"])
        prevention_steps = recommendation.get("prevention_steps") or []
        if prevention_steps:
            lines.extend(["", "재발 방지"])
            lines.extend(f"- {item}" for item in prevention_steps)
        additional_data = recommendation.get("additional_data_needed") or []
        if additional_data:
            lines.extend(["", "추가 필요 데이터"])
            lines.extend(f"- {item}" for item in additional_data)
        if recommendation.get("quality_score") is not None:
            lines.extend(
                [
                    "",
                    "품질 평가",
                    (
                        f"- 점수: {recommendation.get('quality_score')} "
                        f"({recommendation.get('quality_gate_status')})"
                    ),
                    f"- 시도 횟수: {recommendation.get('quality_attempts')}",
                ]
            )
        return "\n".join(lines)
