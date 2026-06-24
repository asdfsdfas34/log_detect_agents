from app.main import AnalyzeRequest, analyze


class FakeGraph:
    def invoke(self, state):
        state["final"] = {
            "executive_summary": "LLM summary",
            "recommended_actions": [
                {"priority": "P1", "action": "LLM+RAG action", "owner": "sre"}
            ],
            "verification_steps": ["LLM verification"],
            "additional_data_needed": None,
            "generated_answer": "LLM generated answer",
            "evidence_bundle": {"recommendation_source": "llm_rag"},
            "saved_recommendation_id": None,
        }
        state["assessment"]["risk_score"] = 10
        state["assessment"]["confidence"] = "low"
        return state


def test_analyze_scenario_pipeline_does_not_overwrite_final(monkeypatch):
    scenario = {
        "fingerprints": [
            {
                "fingerprint": "FP-SCENARIO",
                "occurrence_count": 3,
                "message": "scenario message",
                "log_level": "ERROR",
                "stacktrace": "Traceback",
            }
        ],
        "anomalies": [{"message": "scenario anomaly"}],
        "summary": {
            "risk_score": 90,
            "risk_level": "Critical",
            "detection_status": "detected",
        },
        "recommendation": {
            "fingerprint": "FP-SCENARIO",
            "cause": "Scenario cause",
            "recommendation": "Scenario action",
            "confidence": "HIGH",
        },
        "impacts": [
            {"fingerprint": "FP-SCENARIO", "risk_score": 90, "risk_level": "Critical"}
        ],
    }
    monkeypatch.setattr("app.main.build_graph", lambda: FakeGraph())
    monkeypatch.setattr("app.main.run_detection_pipeline", lambda service_name: scenario)

    response = analyze(AnalyzeRequest(service_name="payment-api"))
    result = response.result

    assert result["final"]["generated_answer"] == "LLM generated answer"
    assert result["final"]["recommended_actions"][0]["action"] == "LLM+RAG action"
    assert result["final"]["verification_steps"] == ["LLM verification"]
    assert result["final"]["evidence_bundle"]["recommendation_source"] == "llm_rag"
    assert "scenario_detection" in result["final"]["evidence_bundle"]
    assert result["final"]["saved_recommendation_id"] is None
