"""AnomalyDetectionAgent implementation."""

from collections import Counter

from app.state import SharedState


class AnomalyDetectionAgent:
    """Detect abnormal patterns from normalized logs and existing analysis outputs."""

    name = "AnomalyDetectionAgent"

    def run(self, state: SharedState) -> SharedState:
        logs = state["evidence"]["normalized_logs"]
        if not logs:
            state["metrics"]["anomaly_score"] = 0.0
            state["decisions"]["assumptions"].append("분석할 로그가 없어 anomaly score를 0으로 설정했습니다.")
            state["decisions"]["agents_run"].append(self.name)
            return state

        level_counter: Counter[str] = Counter(str(log.get("level", "INFO")).upper() for log in logs)
        total = len(logs)
        error_rate = level_counter.get("ERROR", 0) / total
        warn_rate = level_counter.get("WARN", 0) / total

        anomaly_score = round(min(1.0, (error_rate * 0.75) + (warn_rate * 0.25)) * 100, 2)

        if anomaly_score >= 70:
            state["evidence"]["anomalies"].append(
                {
                    "system": (state["scope"].get("systems") or ["unknown"])[0],
                    "severity": "high",
                    "pattern": "error_spike",
                    "message": f"비정상 에러 비율 탐지 (anomaly_score={anomaly_score})",
                }
            )
        elif anomaly_score >= 40:
            state["evidence"]["anomalies"].append(
                {
                    "system": (state["scope"].get("systems") or ["unknown"])[0],
                    "severity": "mid",
                    "pattern": "warning_increase",
                    "message": f"경고 로그 빈도 증가 탐지 (anomaly_score={anomaly_score})",
                }
            )

        state["metrics"]["anomaly_score"] = anomaly_score
        state["decisions"]["agents_run"].append(self.name)
        return state
