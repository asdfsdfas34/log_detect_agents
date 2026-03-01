"""ImpactEvaluationAgent implementation backed by SQLite analysis history."""

from app.db.sqlite_store import fetch_latest_log_analyses, save_impact_evaluation
from app.state import SharedState


class ImpactEvaluationAgent:
    """Compute risk and service metrics from persisted log analyses."""

    name = "ImpactEvaluationAgent"

    def run(self, state: SharedState) -> SharedState:
        systems = state["scope"].get("systems") or []
        stored_analyses = fetch_latest_log_analyses(service_names=systems, limit=20)

        if not stored_analyses:
            state["decisions"]["assumptions"].append(
                "분석 이력이 없어 현재 요청의 anomalies 기준으로 위험도를 산정했습니다."
            )

        anomalies = state["evidence"]["anomalies"]
        logs = state["evidence"]["normalized_logs"]
        total = max(len(logs), 1)

        high_count = sum(1 for a in anomalies if a.get("severity") == "high")
        mid_count = sum(1 for a in anomalies if a.get("severity") == "mid")

        history_risk_signals = 0
        for item in stored_analyses:
            text = item.get("analysis", "").lower()
            history_risk_signals += sum(text.count(token) for token in ["critical", "장애", "timeout", "error"])

        risk_score = min(100, high_count * 25 + mid_count * 12 + history_risk_signals)

        confidence = "low"
        if risk_score >= 70:
            confidence = "high"
        elif risk_score >= 35:
            confidence = "mid"

        rationale = [
            f"high_severity={high_count}",
            f"mid_severity={mid_count}",
            f"history_signals={history_risk_signals}",
            f"history_records={len(stored_analyses)}",
        ]

        state["metrics"] = {
            "error_rate": round(len(anomalies) / total, 3),
            "latency_p95": round(180.0 + (high_count * 35.0) + (mid_count * 10.0), 2),
            "rps": round(max(20.0, 120.0 - (len(anomalies) * 3.5)), 2),
        }
        state["assessment"] = {
            "risk_score": risk_score,
            "confidence": confidence,
            "rationale": rationale,
        }

        target_service = systems[0] if systems else "all"
        save_impact_evaluation(
            service_name=target_service,
            risk_score=risk_score,
            confidence=confidence,
            rationale=", ".join(rationale),
        )

        state["decisions"]["agents_run"].append(self.name)
        return state
