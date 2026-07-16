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
from app.reasoning_events import reasoning_state
from app.state import SharedState
from app.streaming import emit_event
from app.trace_events import record_trace_event, redact_error


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
            skill_name = str(item.get("name") or skill_id)
            operation = operations.get(skill_id)
            reasons = [str(reason) for reason in item.get("reasons", [])]
            span_id = f"{state.get('request_id', '')}:skill:{scope}:{skill_id}"
            self._emit_skill_event(
                state=state,
                item=item,
                agent_name=agent_name,
                scope=scope,
                status="planned" if operation is not None else "selected",
            )
            record_trace_event(
                state,
                kind="skill",
                event_type="skill.planned" if operation is not None else "plan.skill_selected",
                status="planned" if operation is not None else "completed",
                title=f"Skill 선택: {skill_name}",
                summary=(
                    f"{scope} scope에서 {skill_name} 스킬을 "
                    f"{'실행 대상으로 계획' if operation is not None else '선택'}했습니다."
                ),
                agent_name=agent_name,
                component="PatternSkillRunner",
                layer="skill",
                span_id=span_id,
                decision_summary=("선택 근거: " + ", ".join(reasons)) if reasons else None,
                evidence_refs=[skill_id],
                metadata={"skill_id": skill_id, "scope": scope, "score": item.get("score")},
            )
            if operation is None:
                status = "selected"
                result_state = state
            else:
                try:
                    self._emit_skill_event(
                        state=state,
                        item=item,
                        agent_name=agent_name,
                        scope=scope,
                        status="running",
                    )
                    record_trace_event(
                        state,
                        kind="skill",
                        event_type="skill.started",
                        status="running",
                        title=f"Skill 실행 시작: {skill_name}",
                        summary=f"{skill_name} 스킬 실행을 시작합니다.",
                        agent_name=agent_name,
                        component="PatternSkillRunner",
                        layer="skill",
                        span_id=span_id,
                        evidence_refs=[skill_id],
                        metadata={"skill_id": skill_id, "scope": scope},
                    )
                    with reasoning_state(state, agent_name=agent_name):
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
                    self._record_validator_traces(
                        result_state,
                        agent_name=agent_name,
                        skill_name=skill_name,
                        skill_id=skill_id,
                        validator_results=validator_results,
                    )
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
                    record_trace_event(
                        result_state,
                        kind="skill",
                        event_type="skill.completed" if status == "success" else "skill.failed",
                        status="completed" if status == "success" else "failed",
                        title=(
                            f"Skill 실행 완료: {skill_name}"
                            if status == "success"
                            else f"Skill 검증 실패: {skill_name}"
                        ),
                        summary=(
                            f"{skill_name} 스킬 실행이 완료되었습니다."
                            if status == "success"
                            else f"{skill_name} 스킬 실행 후 validator가 실패했습니다."
                        ),
                        agent_name=agent_name,
                        component="PatternSkillRunner",
                        layer="skill",
                        span_id=span_id,
                        evidence_refs=[skill_id],
                        metadata={
                            "skill_id": skill_id,
                            "scope": scope,
                            "failed_validators": len(failed_validators),
                        },
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
                    record_trace_event(
                        state,
                        kind="skill",
                        event_type="skill.failed",
                        status="failed",
                        title=f"Skill 실행 실패: {skill_name}",
                        summary=f"{skill_name} 스킬 실행 중 오류가 발생했습니다.",
                        agent_name=agent_name,
                        component="PatternSkillRunner",
                        layer="skill",
                        span_id=span_id,
                        evidence_refs=[skill_id],
                        error=redact_error(exc),
                        metadata={"skill_id": skill_id, "scope": scope},
                    )
            state = result_state
            scoped_plan = {"selected_skills": [item], "scope": scope}
            recorded = record_skill_executions(
                request_id=str(state.get("request_id", "")),
                plan=scoped_plan,
                agent_name=agent_name,
                scope=scope,
                status=status,
            )
            executions.extend(recorded)
            for execution in recorded:
                self._emit_skill_event_from_execution(execution, item=item)
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
    def _record_validator_traces(
        state: SharedState,
        *,
        agent_name: str,
        skill_name: str,
        skill_id: str,
        validator_results: list[dict[str, Any]],
    ) -> None:
        for result in validator_results:
            passed = bool(result.get("passed"))
            validator_type = str(result.get("validator_type", ""))
            record_trace_event(
                state,
                kind="validation",
                event_type="validator.passed" if passed else "validator.failed",
                status="completed" if passed else "failed",
                title=(
                    f"Validation 통과: {validator_type}"
                    if passed
                    else f"Validation 실패: {validator_type}"
                ),
                summary=str(result.get("message") or validator_type),
                agent_name=agent_name,
                component="SkillValidator",
                layer="skill",
                decision_summary=(
                    None
                    if passed
                    else f"{skill_name} 산출물이 {validator_type} 기준을 충족하지 못했습니다."
                ),
                evidence_refs=[skill_id],
                metadata={
                    "skill_id": skill_id,
                    "validator_type": validator_type,
                    "passed": passed,
                },
            )

    @staticmethod
    def _emit_skill_event(
        *,
        state: SharedState,
        item: dict[str, Any],
        agent_name: str,
        scope: str,
        status: str,
    ) -> None:
        request_id = str(state.get("request_id", ""))
        skill_id = str(item.get("skill_id", ""))
        emit_event(
            "skill",
            {
                "execution_id": (
                    f"{request_id}:{agent_name}:{scope}:{skill_id}:{status}"
                ),
                "request_id": request_id,
                "agent_name": agent_name,
                "scope": scope,
                "skill_id": skill_id,
                "skill_name": str(item.get("name") or skill_id),
                "status": status,
                "score": float(item.get("score", 0)),
                "reason": ", ".join(
                    str(reason) for reason in item.get("reasons", [])
                ),
            },
        )

    @staticmethod
    def _emit_skill_event_from_execution(
        execution: dict[str, Any], *, item: dict[str, Any]
    ) -> None:
        emit_event(
            "skill",
            {
                **execution,
                "skill_name": str(item.get("name") or execution.get("skill_id") or ""),
            },
        )

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
