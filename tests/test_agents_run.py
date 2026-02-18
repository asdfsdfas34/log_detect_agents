from fastapi.testclient import TestClient

from app.main import app


def test_agents_run_returns_stage_outputs(monkeypatch):
    def fake_generate_text(*, messages, model=None, temperature=0.2):
        system = messages[0]["content"]
        if "Log Collector Agent" in system:
            return "normalized logs"
        if "Log Analysis Agent" in system:
            return "analysis result"
        if "Impact Evaluation Agent" in system:
            return "impact result"
        if "Source Code Analysis Agent" in system:
            return "code result"
        return "recommendation result"

    monkeypatch.setattr("app.graph.builder.generate_text", fake_generate_text)

    client = TestClient(app)
    res = client.post(
        "/agents/run",
        json={
            "input": "API latency spike",
            "service_name": "billing-api",
            "raw_logs": ["ERROR timeout", "WARN retry"],
        },
    )

    assert res.status_code == 200
    body = res.json()
    assert body["collected_logs"] == "normalized logs"
    assert body["log_analysis"] == "analysis result"
    assert body["impact_evaluation"] == "impact result"
    assert body["source_code_analysis"] == "code result"
    assert body["recommendation"] == "recommendation result"

