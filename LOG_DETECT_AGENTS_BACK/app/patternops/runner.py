"""PatternOps scoped planner and skill runner."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.patternops.skill_graph import (
    fetch_pattern_skills,
    plan_skill_graphs,
    record_skill_executions,
)
from app.patternops.validators import validate_skill_result
from app.state import SharedState


class PatternSkillRunner:
    """Run selected skill graphs by delegating operations to the host agent.

    In this transition architecture the agent provides concrete operation
    callables. The runner selects scoped skills, dispatches mapped operations,
    records execution status, and exposes graph/artifact/validator metadata.
    """

    def run_for_agent(
        self,
        state: SharedState,
        *,
        agent_name: str,
        scope: str,
        operations: dict[str, Callable[[SharedState], SharedState]] | None = None,
    ) -> SharedState:
        plan = plan_skill_graphs(state, scope=scope)
        operations = operations or {}
        executions: list[dict[str, Any]] = []
        selected_skills = sorted(
            plan.get("selected_skills", []),
            key=lambda item: (int(item.get("priority", 100)), str(item.get("skill_id", ""))),
        )
        for item in selected_skills:
            skill_id = str(item.get("skill_id", ""))
            operation = operations.get(skill_id)
            if operation is None:
                status = "selected"
                result_state = state
            else:
                try:
                    result_state = operation(state)
                    status = "success"
                    validator_results = validate_skill_result(
                        skill_id=skill_id,
                        state=result_state,
                        validators=item.get("validators", []),
                    )
                    result_state["evidence"]["pattern_ops_validator_results"] = [
                        *result_state["evidence"].get(
                            "pattern_ops_validator_results", []
                        ),
                        *validator_results,
                    ]
                    failed_validators = [
                        result for result in validator_results if not result["passed"]
                    ]
                    if failed_validators:
                        status = "failed"
                        for failed in failed_validators:
                            result_state["decisions"]["failures"].append(
                                {
                                    "node": agent_name,
                                    "skill_id": skill_id,
                                    "error": (
                                        f"Validator {failed['validator_type']} failed: "
                                        f"{failed['message']}"
                                    ),
                                    "retry_count": 0,
                                }
                            )
                except Exception as exc:
                    result_state = state
                    status = "failed"
                    state["decisions"]["failures"].append(
                        {
                            "node": agent_name,
                            "skill_id": skill_id,
                            "error": str(exc),
                            "retry_count": 0,
                        }
                    )
            state = result_state
            scoped_plan = {"selected_skills": [item], "scope": scope}
            executions.extend(
                record_skill_executions(
                    request_id=str(state.get("request_id", "")),
                    plan=scoped_plan,
                    agent_name=agent_name,
                    scope=scope,
                    status=status,
                )
            )
        state["evidence"]["pattern_ops_skill_graphs"] = [
            self._skill_summary(skill)
            for skill in fetch_pattern_skills()
        ]
        state["evidence"]["pattern_ops_skill_plan"] = self._merge_scoped_plan(
            state["evidence"].get("pattern_ops_skill_plan", {}),
            scope=scope,
            agent_name=agent_name,
            plan=plan,
        )
        state["evidence"]["pattern_ops_skill_executions"] = [
            *state["evidence"].get("pattern_ops_skill_executions", []),
            *executions,
        ]
        selected_ids = [
            str(item.get("skill_id", ""))
            for item in plan.get("selected_skills", [])
            if item.get("skill_id")
        ]
        state["decisions"]["assumptions"].append(
            f"PatternOps scoped runner agent={agent_name} scope={scope} "
            f"selected={', '.join(selected_ids) or 'none'}"
        )
        return state

    @staticmethod
    def _skill_summary(skill: Any) -> dict[str, Any]:
        return {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "category": skill.category,
            "lifecycle": skill.lifecycle,
            "priority": skill.priority,
            "graph": skill.graph,
            "precondition": skill.precondition,
            "operation": skill.operation,
            "artifact": skill.artifact,
            "validators": skill.validators,
        }

    @staticmethod
    def _merge_scoped_plan(
        existing: dict[str, Any], *, scope: str, agent_name: str, plan: dict[str, Any]
    ) -> dict[str, Any]:
        merged = dict(existing or {})
        scoped = dict(merged.get("scoped_plans", {}))
        scoped[scope] = {"agent_name": agent_name, **plan}
        selected: dict[str, dict[str, Any]] = {}
        for scoped_plan in scoped.values():
            for item in scoped_plan.get("selected_skills", []):
                skill_id = str(item.get("skill_id", ""))
                current = selected.get(skill_id)
                if current is None or float(item.get("score", 0)) > float(
                    current.get("score", 0)
                ):
                    selected[skill_id] = item
        merged.update(
            {
                "scope": "agent_scoped",
                "scoped_plans": scoped,
                "selected_skills": list(selected.values()),
                "edge_decisions": [
                    decision
                    for scoped_plan in scoped.values()
                    for decision in scoped_plan.get("edge_decisions", [])
                ],
                "precondition_decisions": [
                    decision
                    for scoped_plan in scoped.values()
                    for decision in scoped_plan.get("precondition_decisions", [])
                ],
                "excluded_skills": sorted(
                    {
                        item
                        for scoped_plan in scoped.values()
                        for item in scoped_plan.get("excluded_skills", [])
                    }
                ),
            }
        )
        return merged


pattern_skill_runner = PatternSkillRunner()
