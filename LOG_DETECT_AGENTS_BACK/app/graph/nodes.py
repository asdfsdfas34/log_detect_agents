"""Graph nodes with retry and graceful degradation."""

from collections.abc import Callable

from app.agents.anomaly_detection import AnomalyDetectionAgent
from app.agents.knowledge_base_rag import KnowledgeBaseRAGAgent
from app.agents.log_analysis import LogAnalysisAgent
from app.agents.log_collector import LogCollectorAgent
from app.agents.orchestrator import OrchestratorAgent
from app.langsmith_tracing import elapsed_ms, record_agent_event, start_timer
from app.reasoning_events import reasoning_state
from app.state import SharedState
from app.streaming import emit_event
from app.trace_events import record_trace_event, redact_error

_MAX_AGENT_ATTEMPTS = 2

NodeCallable = Callable[[SharedState], SharedState]


orchestrator_agent = OrchestratorAgent()
log_collector_agent = LogCollectorAgent()
log_analysis_agent = LogAnalysisAgent()
anomaly_detection_agent = AnomalyDetectionAgent()
knowledge_base_rag_agent = KnowledgeBaseRAGAgent()


def _run_with_retry(state: SharedState, node_name: str, fn: NodeCallable) -> SharedState:
    """Retry one time and record failures without breaking full flow."""

    attempts = 0
    while attempts < _MAX_AGENT_ATTEMPTS:
        attempt = attempts + 1
        started_at = start_timer()
        request_id = str(state.get("request_id", ""))
        span_id = f"{request_id}:agent:{node_name}:{attempt}"
        record_agent_event(request_id=request_id, agent=node_name, status="started")
        emit_event("stage", node_name)
        if node_name != "OrchestratorAgent":
            record_trace_event(
                state,
                kind="agent",
                event_type="agent.started",
                status="running",
                title=f"{node_name} 실행 시작",
                summary=(
                    f"{node_name}를 실행합니다 (시도 {attempt}/{_MAX_AGENT_ATTEMPTS})."
                ),
                agent_name=node_name,
                component=node_name,
                layer="agent",
                span_id=span_id,
                attempt=attempt,
                max_attempts=_MAX_AGENT_ATTEMPTS,
            )
        try:
            with reasoning_state(state, agent_name=node_name):
                output = fn(state)
            if node_name != "OrchestratorAgent":
                output["orchestration"]["completed_agents"].append(node_name)
            record_agent_event(
                request_id=request_id,
                agent=node_name,
                status="completed",
                elapsed_ms=elapsed_ms(started_at),
            )
            if node_name != "OrchestratorAgent":
                record_trace_event(
                    output,
                    kind="agent",
                    event_type="agent.completed",
                    status="completed",
                    title=f"{node_name} 실행 완료",
                    summary=f"{node_name} 실행을 마쳤습니다.",
                    agent_name=node_name,
                    component=node_name,
                    layer="agent",
                    span_id=span_id,
                    duration_ms=elapsed_ms(started_at),
                    attempt=attempt,
                    max_attempts=_MAX_AGENT_ATTEMPTS,
                )
            return output
        except Exception as exc:  # noqa: BLE001
            attempts += 1
            failed = attempts >= _MAX_AGENT_ATTEMPTS
            record_agent_event(
                request_id=request_id,
                agent=node_name,
                status="retrying" if not failed else "failed",
                elapsed_ms=elapsed_ms(started_at),
                error=str(exc),
            )
            record_trace_event(
                state,
                kind="agent",
                event_type="agent.failed" if failed else "agent.retrying",
                status="failed" if failed else "running",
                title=(
                    f"{node_name} 실행 실패" if failed else f"{node_name} 재시도"
                ),
                summary=(
                    f"{node_name} 실행이 실패해 건너뜁니다."
                    if failed
                    else f"{node_name} 실행이 실패하여 1회 재시도합니다."
                ),
                agent_name=node_name,
                component=node_name,
                layer="agent",
                span_id=span_id,
                duration_ms=elapsed_ms(started_at),
                attempt=attempt,
                max_attempts=_MAX_AGENT_ATTEMPTS,
                error=redact_error(exc),
            )
            if failed:
                state["decisions"]["failures"].append(
                    {
                        "node": node_name,
                        "error": str(exc),
                        "retry_count": 1,
                    }
                )
                state["decisions"]["skipped_agents"].append(node_name)
                state["orchestration"]["completed_agents"].append(node_name)
                return state
    return state


def orchestrator_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "OrchestratorAgent", orchestrator_agent.run)


def collect_logs_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "LogCollectorAgent", log_collector_agent.run)


def analyze_logs_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "LogAnalysisAgent", log_analysis_agent.run)


def anomaly_detection_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "AnomalyDetectionAgent", anomaly_detection_agent.run)


def knowledge_base_rag_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "KnowledgeBaseRAGAgent", knowledge_base_rag_agent.run)
