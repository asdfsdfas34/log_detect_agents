"""Orchestrator agent that controls multi-agent workflow execution."""

from app.state import SharedState


class OrchestratorAgent:
    """Decide which agent should run next and manage workflow state."""

    name = "OrchestratorAgent"
    execution_order = [
        "LogCollectorAgent",
        "LogAnalysisAgent",
        "AnomalyDetectionAgent",
        "ImpactEvaluationAgent",
    ]

    def run(self, state: SharedState) -> SharedState:
        completed = set(state["orchestration"].get("completed_agents", []))

        for agent_name in self.execution_order:
            if agent_name in completed:
                continue

            state["orchestration"]["next_agent"] = agent_name
            state["orchestration"]["pending_agents"] = [
                name
                for name in self.execution_order
                if name not in completed and name != agent_name
            ]
            state["decisions"]["agents_run"].append(self.name)
            return state

        state["orchestration"]["next_agent"] = "END"
        state["orchestration"]["pending_agents"] = []
        state["decisions"]["agents_run"].append(self.name)
        return state
