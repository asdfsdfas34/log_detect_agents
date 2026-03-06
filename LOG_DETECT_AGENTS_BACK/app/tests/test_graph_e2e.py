from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_analyze_orchestrator_flow_and_skip_code_analysis():
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
    assert "SourceCodeAnalysisAgent" in body["decisions"]["skipped_agents"]
    assert "SourceCodeAnalysisAgent" not in body["decisions"]["agents_run"]
    assert "AnomalyDetectionAgent" in body["decisions"]["agents_run"]
    assert "IncidentCorrelationAgent" in body["decisions"]["agents_run"]
    assert "KnowledgeBaseRAGAgent" in body["decisions"]["agents_run"]
    assert body["final"]["generated_answer"] is not None
    assert body["rag"]["saved_to_chromadb"] is False


def test_analyze_can_save_final_answer_to_chromadb():
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
    assert "SourceCodeAnalysisAgent" in body["decisions"]["skipped_agents"]
    assert body["final"]["generated_answer"] is not None
    assert body["rag"]["saved_to_chromadb"] is True
