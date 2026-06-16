from pathlib import Path

from fastapi.testclient import TestClient

from app.db.sqlite_store import save_recommendation_result
from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"


def test_list_saved_recommendations(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    saved_id = save_recommendation_result(
        request_id="req-history",
        service_name="checkout-api",
        goal="history lookup",
        executive_summary="결제 오류",
        recommendation="결제 재시도 로직을 점검하세요",
        recommended_actions=[
            {"priority": "P1", "action": "retry check", "owner": "backend"}
        ],
        verification_steps=["saved lookup"],
        evidence_bundle={"source": "test"},
        risk_score=80,
        confidence="high",
    )

    client = TestClient(app)
    response = client.get(
        "/recommendations", params={"service_name": "checkout-api", "limit": 5}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommendations"][0]["id"] == saved_id
    assert (
        payload["recommendations"][0]["recommendation"]
        == "결제 재시도 로직을 점검하세요"
    )

    monkeypatch.delenv("SQLITE_PATH", raising=False)
