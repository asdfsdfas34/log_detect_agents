"""Orchestrator agent that controls multi-agent workflow execution."""

from app.patternops.skill_graph import plan_skill_graphs
from app.reasoning_events import record_reasoning_event
from app.state import SharedState
from app.trace_events import record_trace_event


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
            record_reasoning_event(
                state,
                kind="planning",
                agent=self.name,
                status="completed",
                title=f"Planning: 다음 Agent로 {agent_name} 선택",
                detail=(
                    f"전체 계획 {len(selected_skill_ids)}개 스킬 중 "
                    f"{len(selected_skill_ids.intersection(agent_skills))}개 관련 스킬을 실행합니다."
                ),
                metadata={
                    "next_agent": agent_name,
                    "selected_skill_ids": sorted(
                        selected_skill_ids.intersection(agent_skills)
                    ),
                },
            )
            matched_skills = sorted(selected_skill_ids.intersection(agent_skills))
            record_trace_event(
                state,
                kind="routing",
                event_type="route.agent_selected",
                status="completed",
                title=f"Routing: {agent_name} 선택",
                summary=(
                    f"실행 순서상 다음 실행자로 {agent_name}를 선택했습니다."
                ),
                agent_name=self.name,
                component="OrchestratorAgent",
                layer="orchestration",
                decision_summary=(
                    "선택 근거 스킬: " + (", ".join(matched_skills) or "fallback")
                ),
                metadata={
                    "next_agent": agent_name,
                    "pending_agents": state["orchestration"]["pending_agents"],
                    "selected_skill_ids": matched_skills,
                },
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
        record_reasoning_event(
            state,
            kind="planning",
            agent=self.name,
            status="completed",
            title="Planning 완료: 실행 계획 종료",
            detail=f"계획된 {len(selected_skill_ids)}개 스킬의 실행 가능 Agent 검토를 마쳤습니다.",
            metadata={"next_agent": "END"},
        )
        record_trace_event(
            state,
            kind="routing",
            event_type="route.end_selected",
            status="completed",
            title="Routing 종료: 실행할 Agent 없음",
            summary="실행 가능한 Agent 스킬이 없어 파이프라인을 종료합니다.",
            agent_name=self.name,
            component="OrchestratorAgent",
            layer="orchestration",
            metadata={"next_agent": "END"},
        )
        return state
