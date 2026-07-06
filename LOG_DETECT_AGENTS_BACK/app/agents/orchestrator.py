"""Orchestrator agent that controls multi-agent workflow execution."""

from app.patternops.skill_graph import plan_skill_graphs
from app.state import SharedState


class OrchestratorAgent:
    """Decide which agent should run next and manage workflow state."""

    name = "OrchestratorAgent"
    execution_order = [
        "LogCollectorAgent",
        "LogAnalysisAgent",
        "AnomalyDetectionAgent",
    ]
    agent_skill_map = {
        "LogCollectorAgent": {"log_collection"},
        "LogAnalysisAgent": {
            "log_normalization",
            "pattern_fingerprint",
            "known_pattern_match",
            "duplicate_pattern_detection",
            "fingerprint_merge",
            "pattern_rule_suggestion",
        },
        "AnomalyDetectionAgent": {"anomaly_detection", "exception_suppression"},
    }

    def run(self, state: SharedState) -> SharedState:
        completed = set(state["orchestration"].get("completed_agents", []))
        global_plan = plan_skill_graphs(state)
        state["evidence"]["pattern_ops_skill_plan"] = {
            **state["evidence"].get("pattern_ops_skill_plan", {}),
            "global_plan": global_plan,
        }
        selected_skill_ids = {
            str(item.get("skill_id", ""))
            for item in global_plan.get("selected_skills", [])
        }

        for agent_name in self.execution_order:
            if agent_name in completed:
                continue
            agent_skills = self.agent_skill_map.get(agent_name, set())
            if selected_skill_ids and not selected_skill_ids.intersection(agent_skills):
                continue

            state["orchestration"]["next_agent"] = agent_name
            state["orchestration"]["pending_agents"] = [
                name
                for name in self.execution_order
                if name not in completed and name != agent_name
            ]
            state["decisions"]["agents_run"].append(self.name)
            state["decisions"]["assumptions"].append(
                "SkillOps global planner selected "
                f"{agent_name} from skills="
                f"{', '.join(sorted(selected_skill_ids.intersection(agent_skills))) or 'fallback'}"
            )
            return state

        for agent_name in self.execution_order:
            if agent_name not in completed and agent_name not in state["decisions"]["skipped_agents"]:
                state["decisions"]["skipped_agents"].append(agent_name)
        state["orchestration"]["next_agent"] = "END"
        state["orchestration"]["pending_agents"] = []
        state["decisions"]["agents_run"].append(self.name)
        state["decisions"]["assumptions"].append(
            "SkillOps global planner reached END with no runnable agent skills."
        )
        return state
