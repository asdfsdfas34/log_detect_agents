import json

from app.agents.recommendation import RecommendationAgent
from app.state import create_initial_state


class FakeMCPClient:
    def __init__(self, openai_response):
        self.openai_response = openai_response
        self.calls = []

    def call_tool(self, tool_name, arguments=None):
        self.calls.append((tool_name, arguments or {}))
        if tool_name == "openai.generate_text":
            if isinstance(self.openai_response, Exception):
                raise self.openai_response
            return self.openai_response
        if tool_name == "sqlite.save_recommendation_result":
            return 77
        raise AssertionError(f"unexpected tool: {tool_name}")


def _state():
    state = create_initial_state(
        goal="payment timeout investigation",
        scope={"systems": ["payment-api"], "time_range": {}, "filters": {}},
        request_id="req-rec",
    )
    state["evidence"]["anomalies"] = [
        {"message": "payment provider timeout", "pattern": "timeout"}
    ]
    state["evidence"]["incident_candidates"] = [
        {"root_cause_hint": "external provider latency"}
    ]
    state["evidence"]["source_code_evidence"] = [
        {"file": "payment_client.py", "symbol": "PaymentClient.call"}
    ]
    state["evidence"]["known_pattern_matches"] = [
        {"pattern_id": "KP-TIMEOUT", "confidence": 0.91}
    ]
    state["metrics"]["anomaly_score"] = 0.82
    state["assessment"]["risk_score"] = 82
    state["assessment"]["confidence"] = "high"
    state["assessment"]["rationale"] = ["Risk Level: High"]
    state["rag"]["related_knowledge"] = ["KC-123 timeout retry case"]
    return state


def test_recommendation_agent_uses_structured_llm_actions(monkeypatch):
    response = json.dumps(
        {
            "executive_summary": "payment-api timeout 재발 가능성이 높습니다.",
            "recommended_actions": [
                {
                    "priority": "P1",
                    "action": "KC-123의 timeout 조정 사례와 현재 provider latency를 비교합니다.",
                    "owner": "sre",
                    "evidence": ["similar_case=KC-123"],
                }
            ],
            "verification_steps": ["동일 fingerprint 발생량 감소 여부를 확인합니다."],
            "prevention_steps": ["provider timeout runbook을 갱신합니다."],
            "additional_data_needed": [],
            "confidence": "high",
        },
        ensure_ascii=False,
    )
    fake = FakeMCPClient(response)
    monkeypatch.setattr("app.agents.recommendation.get_mcp_client", lambda: fake)

    result = RecommendationAgent().run(_state())

    assert result["final"]["recommended_actions"] == [
        {
            "priority": "P1",
            "action": "KC-123의 timeout 조정 사례와 현재 provider latency를 비교합니다.",
            "owner": "sre",
            "evidence": ["similar_case=KC-123"],
        }
    ]
    assert result["final"]["verification_steps"] == [
        "동일 fingerprint 발생량 감소 여부를 확인합니다."
    ]
    assert "에러 재현 시나리오 기반 핫픽스" not in result["final"]["generated_answer"]
    assert result["final"]["evidence_bundle"]["recommendation_source"] == "llm_rag"
    saved_call = [call for call in fake.calls if call[0] == "sqlite.save_recommendation_result"][0]
    assert saved_call[1]["recommended_actions"] == result["final"]["recommended_actions"]


def test_recommendation_agent_falls_back_when_structured_json_invalid(monkeypatch):
    fake = FakeMCPClient("not-json")
    monkeypatch.setattr("app.agents.recommendation.get_mcp_client", lambda: fake)

    result = RecommendationAgent().run(_state())

    assert result["final"]["recommended_actions"][0]["action"] == "에러 재현 시나리오 기반 핫픽스 후보 코드 검토"
    assert result["final"]["evidence_bundle"]["recommendation_source"] == "fallback"
    assert any("fallback" in item for item in result["decisions"]["assumptions"])
