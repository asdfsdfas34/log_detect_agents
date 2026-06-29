from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
REMOVED_CODE_AGENT = "Source" + "Code" + "Analysis" + "Agent"


def test_analyze_orchestrator_flow_without_code_analysis():
    res = client.post(
        "/analyze",
        json={
            "service_name": "billing-api",
            "goal": "payment auth exception risk investigation",
            "scope": {
                "systems": ["billing-api", "auth-api"],
                "time_range": {"from": "2026-01-01T00:00:00", "to": "2026-01-01T01:00:00"},
                "filters": {"env": "prod"},
            },
            "save_to_chromadb": False,
        },
    )

    assert res.status_code == 200
    body = res.json()["result"]
    assert REMOVED_CODE_AGENT not in body["decisions"]["skipped_agents"]
    assert REMOVED_CODE_AGENT not in body["decisions"]["agents_run"]
    assert "AnomalyDetectionAgent" in body["decisions"]["agents_run"]
    assert "KnowledgeBaseRAGAgent" in body["decisions"]["agents_run"]
    assert "RecommendationAgent" in body["decisions"]["skipped_agents"]
    assert body["final"]["generated_answer"] is None
    assert body["final"]["evidence_bundle"] is not None
    assert "known_pattern_summary" in body["final"]["evidence_bundle"]
    assert body["rag"]["saved_to_chromadb"] is False


def test_analyze_does_not_save_final_answer_to_chromadb_without_recommendation():
    res = client.post(
        "/analyze",
        json={
            "service_name": "api",
            "goal": "auth 이슈 대응",
            "save_to_chromadb": True,
            "scope": {
                "systems": ["api"],
                "time_range": {"from": "2026-01-01T00:00:00", "to": "2026-01-01T01:00:00"},
                "filters": {"disable_stack_traces": True},
            },
        },
    )

    assert res.status_code == 200
    body = res.json()["result"]
    assert REMOVED_CODE_AGENT not in body["decisions"]["skipped_agents"]
    assert "RecommendationAgent" in body["decisions"]["skipped_agents"]
    assert body["final"]["generated_answer"] is None
    assert body["final"]["evidence_bundle"] is not None
    assert body["rag"]["saved_to_chromadb"] is False
