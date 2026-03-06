"""Orchestrator agent that controls multi-agent workflow execution."""

from app.state import SharedState


class OrchestratorAgent:
    """Decide which agent should run next and manage skip/failure handling."""

    name = "OrchestratorAgent"
    execution_order = [
        "LogCollectorAgent",
        "LogAnalysisAgent",
        "AnomalyDetectionAgent",
        "IncidentCorrelationAgent",
        "ImpactEvaluationAgent",
        "SourceCodeAnalysisAgent",
        "KnowledgeBaseRAGAgent",
        "RecommendationAgent",
    ]

    def run(self, state: SharedState) -> SharedState:
        completed = set(state["orchestration"].get("completed_agents", []))

        for agent_name in self.execution_order:
            if agent_name in completed:
                continue

            if agent_name == "SourceCodeAnalysisAgent":
                if agent_name not in state["decisions"]["skipped_agents"]:
                    state["decisions"]["skipped_agents"].append(agent_name)
                state["decisions"]["assumptions"].append(
                    "요청 정책에 따라 source_code_analysis 단계는 항상 생략합니다."
                )
                state["orchestration"]["completed_agents"].append(agent_name)
                completed.add(agent_name)
                continue

            state["orchestration"]["next_agent"] = agent_name
            state["orchestration"]["pending_agents"] = [
                name for name in self.execution_order if name not in completed and name != agent_name
            ]
            state["decisions"]["agents_run"].append(self.name)
            return state

        state["orchestration"]["next_agent"] = "END"
        state["orchestration"]["pending_agents"] = []
        state["decisions"]["agents_run"].append(self.name)
        return state
