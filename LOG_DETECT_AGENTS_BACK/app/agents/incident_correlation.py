"""IncidentCorrelationAgent implementation."""

from collections import defaultdict

from app.state import SharedState


class IncidentCorrelationAgent:
    """Group related anomalies and logs into incident candidates."""

    name = "IncidentCorrelationAgent"

    def run(self, state: SharedState) -> SharedState:
        logs = state["evidence"]["normalized_logs"]
        grouped: dict[str, list[dict]] = defaultdict(list)

        for log in logs:
            service = str(log.get("system") or "unknown-service")
            grouped[service].append(log)

        incident_candidates: list[dict] = []
        for service, items in grouped.items():
            error_logs = [item for item in items if str(item.get("level", "")).upper() == "ERROR"]
            if not error_logs:
                continue

            incident_candidates.append(
                {
                    "service": service,
                    "window_start": error_logs[-1].get("timestamp"),
                    "window_end": error_logs[0].get("timestamp"),
                    "error_count": len(error_logs),
                    "root_cause_hint": error_logs[0].get("message", ""),
                }
            )

        state["evidence"]["incident_candidates"] = incident_candidates
        if incident_candidates:
            state["assessment"]["rationale"].append(
                f"incident_candidates={len(incident_candidates)}"
            )

        state["decisions"]["agents_run"].append(self.name)
        return state
