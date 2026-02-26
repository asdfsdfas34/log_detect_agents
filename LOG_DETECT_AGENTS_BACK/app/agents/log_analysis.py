"""Stub LogAnalysisAgent implementation."""

from collections import Counter

from app.state import SharedState


class LogAnalysisAgent:
    """Create anomaly and cluster information from normalized logs."""

    name = "LogAnalysisAgent"

    def run(self, state: SharedState) -> SharedState:
        logs = state["evidence"]["normalized_logs"]
        anomalies: list[dict] = []
        cluster_counter: Counter[str] = Counter()

        for log in logs:
            msg = str(log.get("message", "")).lower()
            if "error" in msg or "exception" in msg:
                severity = "high" if "exception" in msg else "mid"
                anomalies.append(
                    {
                        "system": log.get("system"),
                        "severity": severity,
                        "pattern": "error_exception",
                        "message": log.get("message"),
                    }
                )
                cluster_counter[f"error:{severity}"] += 1
            elif log.get("level") == "WARN":
                cluster_counter["warn:retry"] += 1
            else:
                cluster_counter["info:heartbeat"] += 1

        state["evidence"]["anomalies"] = anomalies
        state["evidence"]["clusters"] = [
            {"cluster": key, "count": value} for key, value in sorted(cluster_counter.items())
        ]
        state["decisions"]["agents_run"].append(self.name)
        return state
