from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_analyze_always_skips_code_analysis_and_returns_generated_answer():
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
        },
    )

    assert res.status_code == 200
    body = res.json()["result"]
    assert "SourceCodeAnalysisAgent" in body["decisions"]["skipped_agents"]
    assert "SourceCodeAnalysisAgent" not in body["decisions"]["agents_run"]
    assert body["final"]["generated_answer"] is not None
    assert body["final"]["recommended_actions"] is not None


def test_analyze_skips_code_analysis_without_stack_trace_when_forced():
    res = client.post(
        "/analyze",
        json={
            "service_name": "api",
            "goal": "auth 이슈 대응",
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
