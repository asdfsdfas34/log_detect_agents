"""Stub SourceCodeAnalysisAgent implementation."""

from app.state import SharedState


class SourceCodeAnalysisAgent:
    """Derive dummy source-code candidates from stack traces."""

    name = "SourceCodeAnalysisAgent"

    def run(self, state: SharedState) -> SharedState:
        traces = state["evidence"]["stack_traces"]
        candidates = []
        for idx, trace in enumerate(traces[:5], start=1):
            candidates.append(
                {
                    "file": f"app/services/payment_auth_{idx}.py",
                    "function": "process_request",
                    "evidence": trace,
                }
            )

        state["decisions"]["agents_run"].append(self.name)
        state["decisions"]["assumptions"].append(
            f"source_candidates={len(candidates)} derived from stack traces"
        )
        return state
