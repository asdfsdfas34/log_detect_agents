"""RecommendationAgent implementation using MCP tools."""

import json

from app.mcp import get_mcp_client
from app.state import SharedState


class RecommendationAgent:
    """Build actionable remediation outputs."""

    name = "RecommendationAgent"

    def run(self, state: SharedState) -> SharedState:
        risk = state["assessment"]["risk_score"] or 0
        anomalies = state["evidence"]["anomalies"]
        impact_text = "\n".join(state["assessment"]["rationale"])
        metrics = state["metrics"]

        needs_data = any("추가 데이터 필요" in item for item in state["decisions"]["assumptions"])

        actions = [
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
        ]

        verification = [
            "수정 배포 후 동일 time_range에서 error/exception 재발 여부 확인",
            "latency_p95, error_rate, rps 지표 비교",
            "회귀 테스트 및 운영 알람 룰 점검",
        ]

        additional_data = None
        if needs_data:
            additional_data = ["stack trace 원문", "실패 요청 샘플 payload", "배포 변경 이력"]

        mcp = get_mcp_client()
        related = mcp.call_tool(
            "chromadb.find_related_analyses",
            {"query": state["goal"], "n_results": 3},
        )

        recommendation_prompt = (
            "다음 장애 영향 평가 결과를 바탕으로 운영자가 바로 활용할 수 있는 한국어 권고안을 작성하세요.\n"
            "반드시 포함: 1) 한 줄 요약 2) 즉시 조치 3) 검증 방법 4) 재발 방지.\n\n"
            f"영향 평가 근거: {impact_text}\n"
            f"리스크 점수: {risk}\n"
            f"지표: {json.dumps(metrics, ensure_ascii=False)}\n"
            f"이상 징후 수: {len(anomalies)}\n"
            f"유사 과거 분석: {json.dumps(related, ensure_ascii=False)}"
        )

        try:
            generated_answer = mcp.call_tool(
                "openai.generate_text",
                {
                    "messages": [
                        {
                            "role": "system",
                            "content": "당신은 장애 대응을 지원하는 SRE Recommendation Agent 입니다.",
                        },
                        {"role": "user", "content": recommendation_prompt},
                    ],
                    "temperature": 0.1,
                },
            )
        except Exception as exc:  # noqa: BLE001
            generated_answer = (
                "OpenAI 추천 생성에 실패해 기본 권고안을 제공합니다. "
                f"error={exc}; risk={risk}; anomalies={len(anomalies)}"
            )
            state["decisions"]["assumptions"].append("OpenAI API 호출 실패로 recommendation fallback을 사용했습니다.")

        state["final"] = {
            "executive_summary": (
                f"총 {len(anomalies)}건 이상 패턴이 탐지되었고 위험도는 {risk}/100 입니다."
            ),
            "recommended_actions": actions,
            "verification_steps": verification,
            "additional_data_needed": additional_data,
            "generated_answer": generated_answer,
        }
        state["decisions"]["agents_run"].append(self.name)
        return state
