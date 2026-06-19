"""RecommendationAgent implementation using MCP tools."""

from __future__ import annotations

import json
import re
from typing import Any

from app.mcp import get_mcp_client
from app.state import SharedState

_REQUIRED_ACTION_KEYS = {"priority", "action", "owner"}


class RecommendationAgent:
    """Build actionable remediation outputs."""

    name = "RecommendationAgent"

    def run(self, state: SharedState) -> SharedState:
        risk = state["assessment"]["risk_score"] or 0
        anomalies = state["evidence"]["anomalies"]
        impact_text = "\n".join(state["assessment"]["rationale"])
        metrics = state["metrics"]
        incidents = state["evidence"].get("incident_candidates", [])
        source_evidence = state["evidence"].get("source_code_evidence", [])
        known_matches = state["evidence"].get("known_pattern_matches", [])

        needs_data = any(
            "추가 데이터 필요" in item for item in state["decisions"]["assumptions"]
        )

        mcp = get_mcp_client()
        related = state.get("rag", {}).get("related_knowledge", [])

        evidence_bundle = {
            "core_logs": [item.get("message") for item in anomalies[:5]],
            "anomaly_score": state["metrics"].get("anomaly_score"),
            "risk_score": risk,
            "incident_candidates": incidents[:3],
            "source_code_evidence": source_evidence[:5],
            "known_pattern_summary": {
                "total_matches": len(known_matches),
                "suppressed": len(state["evidence"].get("suppressed_logs", [])),
            },
            "similar_cases": related,
        }

        try:
            raw_response = mcp.call_tool(
                "openai.generate_text",
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "당신은 장애 대응을 지원하는 SRE Recommendation Agent 입니다. "
                                "응답은 반드시 JSON 객체 하나만 반환하세요."
                            ),
                        },
                        {
                            "role": "user",
                            "content": self._build_structured_prompt(
                                impact_text=impact_text,
                                metrics=metrics,
                                evidence_bundle=evidence_bundle,
                                needs_data=needs_data,
                            ),
                        },
                    ],
                    "temperature": 0.1,
                },
            )
            recommendation = self._parse_structured_recommendation(raw_response)
        except Exception as exc:  # noqa: BLE001
            recommendation = self._fallback_recommendation(
                risk=risk, anomalies=anomalies, needs_data=needs_data
            )
            state["decisions"]["assumptions"].append(
                f"LLM/RAG structured recommendation 실패로 fallback을 사용했습니다: {exc}"
            )

        executive_summary = recommendation["executive_summary"]
        actions = recommendation["recommended_actions"]
        verification = recommendation["verification_steps"]
        additional_data = recommendation["additional_data_needed"]
        generated_answer = self._render_generated_answer(recommendation)
        evidence_bundle["recommendation_source"] = recommendation["source"]
        if recommendation.get("prevention_steps"):
            evidence_bundle["prevention_steps"] = recommendation["prevention_steps"]

        state["final"] = {
            "executive_summary": executive_summary,
            "recommended_actions": actions,
            "verification_steps": verification,
            "additional_data_needed": additional_data,
            "generated_answer": generated_answer,
            "evidence_bundle": evidence_bundle,
            "saved_recommendation_id": None,
        }

        target_service = (state["scope"].get("systems") or ["all"])[0]
        try:
            saved_id = mcp.call_tool(
                "sqlite.save_recommendation_result",
                {
                    "request_id": state.get("request_id", ""),
                    "service_name": target_service,
                    "goal": state.get("goal", ""),
                    "executive_summary": executive_summary,
                    "recommendation": generated_answer,
                    "recommended_actions": actions,
                    "verification_steps": verification,
                    "evidence_bundle": evidence_bundle,
                    "risk_score": risk,
                    "confidence": state["assessment"].get("confidence"),
                },
            )
            state["final"]["saved_recommendation_id"] = saved_id
        except Exception as exc:  # noqa: BLE001
            state["decisions"]["failures"].append(
                {
                    "node": self.name,
                    "error": f"recommendation 저장 실패: {exc}",
                    "retry_count": 0,
                }
            )

        state["decisions"]["agents_run"].append(self.name)
        return state

    @staticmethod
    def _build_structured_prompt(
        *,
        impact_text: str,
        metrics: dict[str, Any],
        evidence_bundle: dict[str, Any],
        needs_data: bool,
    ) -> str:
        schema = {
            "executive_summary": "string: 한 줄 요약",
            "recommended_actions": [
                {
                    "priority": "P1|P2|P3",
                    "action": "string: 근거 기반 즉시 조치",
                    "owner": "backend|sre|service-owner|data|security",
                    "evidence": ["string"],
                }
            ],
            "verification_steps": ["string"],
            "prevention_steps": ["string"],
            "additional_data_needed": ["string"],
            "confidence": "low|mid|high",
        }
        return (
            "다음 evidence bundle과 RAG 유사 사례를 바탕으로 추천안을 생성하세요.\n"
            "규칙:\n"
            "- 반드시 아래 JSON schema와 호환되는 JSON 객체 하나만 반환하세요.\n"
            "- markdown, 설명 문장, 코드블록은 포함하지 마세요.\n"
            "- recommended_actions와 verification_steps는 비어 있으면 안 됩니다.\n"
            "- 조치는 evidence_bundle과 similar_cases에 있는 근거를 우선 사용하세요.\n"
            "- 인프라 변경, DB 스키마 임의 변경, 시크릿/인증 정보 회전, 파괴적 운영 명령은 제안하지 마세요.\n"
            "- 추가 데이터가 필요한 경우 additional_data_needed에만 적고, 추측을 단정하지 마세요.\n\n"
            f"추가 데이터 필요 여부: {needs_data}\n"
            f"JSON schema: {json.dumps(schema, ensure_ascii=False)}\n"
            f"영향 평가 근거: {impact_text}\n"
            f"지표: {json.dumps(metrics, ensure_ascii=False)}\n"
            f"evidence_bundle: {json.dumps(evidence_bundle, ensure_ascii=False)}"
        )

    def _parse_structured_recommendation(self, raw_response: Any) -> dict[str, Any]:
        payload = self._load_json_object(str(raw_response or ""))
        executive_summary = self._required_text(payload, "executive_summary")
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
            "recommended_actions": recommended_actions,
            "verification_steps": verification_steps,
            "prevention_steps": prevention_steps,
            "additional_data_needed": additional_data_needed or None,
            "confidence": confidence,
            "source": "llm_rag",
        }

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
                raise ValueError("LLM 응답에서 JSON 객체를 찾을 수 없습니다.") from exc
            parsed = json.loads(text[start : end + 1])
        if not isinstance(parsed, dict):
            raise ValueError("LLM 응답 JSON은 객체여야 합니다.")
        return parsed

    @staticmethod
    def _required_text(payload: dict[str, Any], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"필수 문자열 필드가 누락되었습니다: {key}")
        return value.strip()

    @staticmethod
    def _validate_actions(value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, list) or not value:
            raise ValueError("recommended_actions는 비어 있지 않은 list여야 합니다.")
        actions: list[dict[str, Any]] = []
        for item in value:
            if not isinstance(item, dict):
                raise ValueError("recommended_actions 항목은 객체여야 합니다.")
            missing = [
                key
                for key in _REQUIRED_ACTION_KEYS
                if not isinstance(item.get(key), str) or not item.get(key, "").strip()
            ]
            if missing:
                raise ValueError(f"recommended_actions 필수 필드 누락: {missing}")
            action = {
                "priority": item["priority"].strip(),
                "action": item["action"].strip(),
                "owner": item["owner"].strip(),
            }
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
            raise ValueError(f"{field_name}는 list여야 합니다.")
        items = [str(item).strip() for item in value if str(item).strip()]
        if required and not items:
            raise ValueError(f"{field_name}는 비어 있으면 안 됩니다.")
        return items

    @staticmethod
    def _fallback_recommendation(
        *, risk: int, anomalies: list[dict], needs_data: bool
    ) -> dict[str, Any]:
        additional_data = (
            ["stack trace 원문", "실패 요청 샘플 payload", "배포 변경 이력"]
            if needs_data
            else None
        )
        return {
            "executive_summary": (
                f"총 {len(anomalies)}건 이상 패턴이 탐지되었고 위험도는 {risk}/100 입니다."
            ),
            "recommended_actions": [
                {
                    "priority": "P1" if risk >= 70 else "P2",
                    "action": "에러 재현 시나리오 기반 핫픽스 후보 코드 검토",
                    "owner": "backend",
                },
                {
                    "priority": "P2",
                    "action": "로그 파이프라인 필드 정합성 점검 및 알람 임계값 재조정",
                    "owner": "sre",
                },
            ],
            "verification_steps": [
                "수정 배포 후 동일 time_range에서 error/exception 재발 여부 확인",
                "latency_p95, error_rate, rps 지표 비교",
                "회귀 테스트 및 운영 알람 룰 점검",
            ],
            "prevention_steps": [],
            "additional_data_needed": additional_data,
            "confidence": "mid",
            "source": "fallback",
        }

    @staticmethod
    def _render_generated_answer(recommendation: dict[str, Any]) -> str:
        lines = [
            "한 줄 요약",
            f"- {recommendation['executive_summary']}",
            "",
            "즉시 조치",
        ]
        lines.extend(
            f"- [{item['priority']}] {item['action']} (owner: {item['owner']})"
            for item in recommendation["recommended_actions"]
        )
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
        return "\n".join(lines)
