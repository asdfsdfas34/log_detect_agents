import json

from app.agents.recommendation import RecommendationAgent
from app.state import create_initial_state


class FakeMCPClient:
    def __init__(self, openai_responses):
        self.openai_responses = list(openai_responses)
        self.calls = []

    def call_tool(self, tool_name, arguments=None):
        self.calls.append((tool_name, arguments or {}))
        if tool_name == "openai.generate_text":
            response = self.openai_responses.pop(0)
            if isinstance(response, Exception):
                raise response
            return response
        raise AssertionError(f"unexpected tool: {tool_name}")


def _recommendation(action: str = "timeout 및 retry 정책을 조정합니다") -> str:
    return json.dumps(
        {
            "executive_summary": "payment-api에서 provider timeout 장애가 반복 발생했습니다.",
            "root_cause_analysis": (
                "payment provider timeout 메시지와 timeout fingerprint, 유사 케이스 "
                "KC-123을 보면 PaymentClient.call 구간의 외부 provider 지연 가능성이 높습니다."
            ),
            "impact_analysis": "payment-api는 사용자 결제 흐름에 영향을 주므로 위험도가 높습니다.",
            "recommended_actions": [
                {
                    "priority": "P1",
                    "action": action,
                    "reason": "현재 로그에서 동일 timeout fingerprint가 반복됩니다.",
                    "target": "payment_client.py PaymentClient.call",
                    "owner": "sre",
                    "expected_effect": "반복 timeout 장애 발생률을 낮춥니다.",
                    "risk": "배포 전 retry 증폭 여부를 검증해야 합니다.",
                    "evidence": ["similar_case=KC-123", "fingerprint=timeout"],
                }
            ],
            "verification_steps": [
                "timeout fingerprint 발생 건수가 감소했는지 확인합니다.",
                "payment provider timeout 로그가 재발하지 않는지 확인합니다.",
            ],
            "prevention_steps": ["provider timeout runbook을 갱신합니다."],
            "additional_data_needed": [],
            "confidence": "high",
        },
        ensure_ascii=False,
    )


def _weak_recommendation() -> str:
    return json.dumps(
        {
            "executive_summary": "payment-api에서 timeout이 발생했습니다.",
            "root_cause_analysis": "외부 provider 지연 가능성이 있습니다.",
            "impact_analysis": "결제 흐름에 영향이 있습니다.",
            "recommended_actions": [
                {
                    "priority": "P1",
                    "action": "timeout 설정을 확인합니다.",
                    "owner": "sre",
                }
            ],
            "verification_steps": ["로그를 확인합니다."],
            "prevention_steps": [],
            "additional_data_needed": [],
            "confidence": "mid",
        },
        ensure_ascii=False,
    )


def _evaluation(score: int, passed: bool, feedback: str = "good") -> str:
    rubric_scores = {}
    remaining = score
    for key, max_score in (
        ("root_cause", 25),
        ("actionability", 25),
        ("verification", 20),
        ("prevention", 15),
        ("safety", 15),
    ):
        value = min(max_score, max(0, remaining))
        rubric_scores[key] = value
        remaining -= value
    return json.dumps(
        {
            "rubric_scores": rubric_scores,
            "passed": passed,
            "missing_points": [] if passed else ["verification too generic"],
            "weak_points": [] if passed else ["actions need stronger evidence links"],
            "feedback": feedback,
        },
        ensure_ascii=False,
    )


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
    state["rag"]["related_knowledge"] = [
        {"card_id": "KC-123", "resolution_method": "provider SLA 확인 후 timeout을 조정함"}
    ]
    return state


def test_recommendation_agent_uses_structured_llm_actions(monkeypatch):
    fake = FakeMCPClient([_recommendation(), _evaluation(92, True)])
    monkeypatch.setattr("app.agents.recommendation.get_mcp_client", lambda: fake)

    result = RecommendationAgent().run(_state())

    assert result["final"]["recommended_actions"][0]["action"] == (
        "timeout 및 retry 정책을 조정합니다"
    )
    assert result["final"]["recommended_actions"][0]["reason"] == (
        "현재 로그에서 동일 timeout fingerprint가 반복됩니다."
    )
    assert result["final"]["verification_steps"] == [
        "timeout fingerprint 발생 건수가 감소했는지 확인합니다.",
        "payment provider timeout 로그가 재발하지 않는지 확인합니다.",
    ]
    assert "대표 오류 시나리오를 재현" not in result["final"]["generated_answer"]
    assert result["final"]["evidence_bundle"]["recommendation_source"] == "llm_rag"
    assert result["final"]["evidence_bundle"]["quality_score"] == 92
    assert result["final"]["evidence_bundle"]["quality_gate_status"] == "passed"
    assert result["final"]["evidence_bundle"]["quality_attempts"] == 1
    assert result["final"]["evidence_bundle"]["referenced_knowledge_card_ids"] == [
        "KC-123"
    ]
    assert "참조 Knowledge Card\n- KC-123" in result["final"]["generated_answer"]
    assert not any(call[0] == "sqlite.save_recommendation_result" for call in fake.calls)
    assert result["final"]["saved_recommendation_id"] is None


def test_recommendation_agent_retries_until_quality_threshold(monkeypatch):
    fake = FakeMCPClient(
        [
            _recommendation("timeout 원인을 검토합니다"),
            _evaluation(72, False, "구체적인 수정 대상과 검증 방법을 추가하세요."),
            _recommendation("PaymentClient.call timeout 처리 로직을 보강합니다"),
            _evaluation(92, True),
        ]
    )
    monkeypatch.setattr("app.agents.recommendation.get_mcp_client", lambda: fake)

    result = RecommendationAgent().run(_state())

    assert result["final"]["recommended_actions"][0]["action"] == (
        "PaymentClient.call timeout 처리 로직을 보강합니다"
    )
    assert result["final"]["evidence_bundle"]["quality_score"] == 92
    assert result["final"]["evidence_bundle"]["quality_attempts"] == 2
    assert len([call for call in fake.calls if call[0] == "openai.generate_text"]) == 4
    reasoning_events = result["evidence"]["agent_reasoning_events"]
    assert any(
        event["kind"] == "self_correction"
        and event["status"] == "running"
        and event["metadata"]["attempt"] == 2
        for event in reasoning_events
    )
    assert any(
        event["kind"] == "self_correction"
        and event["status"] == "completed"
        and event["metadata"]["score"] == 92
        for event in reasoning_events
    )


def test_recommendation_agent_hard_fail_overrides_high_score(monkeypatch):
    fake = FakeMCPClient(
        [
            _weak_recommendation(),
            _evaluation(92, True, "좋습니다."),
            _recommendation("PaymentClient.call timeout 처리 로직을 보강합니다"),
            _evaluation(92, True),
        ]
    )
    monkeypatch.setattr("app.agents.recommendation.get_mcp_client", lambda: fake)

    result = RecommendationAgent().run(_state())

    assert result["final"]["recommended_actions"][0]["action"] == (
        "PaymentClient.call timeout 처리 로직을 보강합니다"
    )
    assert result["final"]["evidence_bundle"]["quality_score"] == 92
    assert result["final"]["evidence_bundle"]["quality_attempts"] == 2


def test_recommendation_agent_easy_perfect_score_triggers_retry(monkeypatch):
    fake = FakeMCPClient(
        [
            _recommendation(),
            _evaluation(100, True, "완벽합니다."),
            _recommendation("PaymentClient.call timeout 처리 로직을 보강합니다"),
            _evaluation(92, True),
        ]
    )
    monkeypatch.setattr("app.agents.recommendation.get_mcp_client", lambda: fake)

    result = RecommendationAgent().run(_state())
    evidence = result["final"]["evidence_bundle"]

    assert evidence["quality_score"] == 92
    assert evidence["quality_gate_status"] == "passed"
    assert evidence["quality_attempts"] == 2
    scores = [
        event["metadata"]["score"]
        for event in result["evidence"]["agent_reasoning_events"]
        if event["kind"] == "self_correction" and "score" in event["metadata"]
    ]
    assert scores == [89, 92]


def test_recommendation_agent_falls_back_when_structured_json_invalid(monkeypatch):
    fake = FakeMCPClient(["not-json", "not-json", "not-json"])
    monkeypatch.setattr("app.agents.recommendation.get_mcp_client", lambda: fake)

    result = RecommendationAgent().run(_state())

    assert result["final"]["recommended_actions"][0]["action"].startswith(
        "대표 오류 시나리오를 재현"
    )
    assert result["final"]["evidence_bundle"]["recommendation_source"] == "fallback"
    assert result["final"]["evidence_bundle"]["quality_gate_status"] == "fallback"
    assert any("fallback" in item for item in result["decisions"]["assumptions"])
