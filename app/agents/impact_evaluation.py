"""Stub ImpactEvaluationAgent implementation."""

from app.state import SharedState


class ImpactEvaluationAgent:
    """Compute risk and service metrics from anomaly evidence."""

    name = "ImpactEvaluationAgent"

    def run(self, state: SharedState) -> SharedState:
        anomalies = state["evidence"]["anomalies"]
        logs = state["evidence"]["normalized_logs"]
        total = max(len(logs), 1)
        high_count = sum(1 for a in anomalies if a.get("severity") == "high")
        risk_score = min(100, len(anomalies) * 10 + high_count * 15)

        confidence = "low"
        if risk_score >= 70:
            confidence = "high"
        elif risk_score >= 30:
            confidence = "mid"

        state["metrics"] = {
            "error_rate": round(len(anomalies) / total, 3),
            "latency_p95": 180.0 + (high_count * 25.0),
            "rps": 110.0 - min(60.0, float(len(anomalies) * 2)),
        }
        state["assessment"] = {
            "risk_score": risk_score,
            "confidence": confidence,
            "rationale": [
                f"anomalies={len(anomalies)}",
                f"high_severity={high_count}",
            ],
        }
        state["decisions"]["agents_run"].append(self.name)
        return state
