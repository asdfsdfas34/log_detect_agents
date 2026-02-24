"""Stub RecommendationAgent implementation."""

from app.state import SharedState


class RecommendationAgent:
    """Build actionable remediation outputs."""

    name = "RecommendationAgent"

    def run(self, state: SharedState) -> SharedState:
        risk = state["assessment"]["risk_score"] or 0
        anomalies = state["evidence"]["anomalies"]
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

        state["final"] = {
            "executive_summary": (
                f"총 {len(anomalies)}건 이상 패턴이 탐지되었고 위험도는 {risk}/100 입니다."
            ),
            "recommended_actions": actions,
            "verification_steps": verification,
            "additional_data_needed": additional_data,
        }
        state["decisions"]["agents_run"].append(self.name)
        return state
