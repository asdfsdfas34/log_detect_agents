"""Stub SourceCodeAnalysisAgent implementation."""

from app.state import SharedState


class SourceCodeAnalysisAgent:
    """Derive source-code evidence candidates from stack traces and incident hints."""

    name = "SourceCodeAnalysisAgent"

    def run(self, state: SharedState) -> SharedState:
        traces = state["evidence"]["stack_traces"]
        anomalies = state["evidence"].get("anomalies", [])
        incidents = state["evidence"].get("incident_candidates", [])

        candidates: list[dict] = []
        for idx, trace in enumerate(traces[:5], start=1):
            candidates.append(
                {
                    "file": f"app/services/payment_auth_{idx}.py",
                    "function": "process_request",
                    "evidence": trace,
                }
            )

        for idx, anomaly in enumerate(anomalies[:5], start=1):
            candidates.append(
                {
                    "file": f"app/services/anomaly_handler_{idx}.py",
                    "function": "handle_log_anomaly",
                    "evidence": anomaly.get("message", ""),
                }
            )

        for idx, incident in enumerate(incidents[:3], start=1):
            candidates.append(
                {
                    "file": f"app/services/incident_router_{idx}.py",
                    "function": "correlate_incident",
                    "evidence": incident.get("root_cause_hint", ""),
                }
            )

        state["evidence"]["source_code_evidence"] = candidates

        state["decisions"]["agents_run"].append(self.name)
        state["decisions"]["assumptions"].append(
            f"source_candidates={len(candidates)} derived from stack traces/anomalies/incidents"
        )
        return state
