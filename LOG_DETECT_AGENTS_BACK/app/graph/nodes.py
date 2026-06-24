"""Graph nodes with retry and graceful degradation."""

from collections.abc import Callable

from app.agents.anomaly_detection import AnomalyDetectionAgent
from app.agents.impact_evaluation import ImpactEvaluationAgent
from app.agents.knowledge_base_rag import KnowledgeBaseRAGAgent
from app.agents.log_analysis import LogAnalysisAgent
from app.agents.log_collector import LogCollectorAgent
from app.agents.orchestrator import OrchestratorAgent
from app.langsmith_tracing import elapsed_ms, record_agent_event, start_timer
from app.state import SharedState

NodeCallable = Callable[[SharedState], SharedState]


orchestrator_agent = OrchestratorAgent()
log_collector_agent = LogCollectorAgent()
log_analysis_agent = LogAnalysisAgent()
anomaly_detection_agent = AnomalyDetectionAgent()
impact_evaluation_agent = ImpactEvaluationAgent()
knowledge_base_rag_agent = KnowledgeBaseRAGAgent()


def _run_with_retry(state: SharedState, node_name: str, fn: NodeCallable) -> SharedState:
    """Retry one time and record failures without breaking full flow."""

    attempts = 0
    while attempts < 2:
        started_at = start_timer()
        request_id = str(state.get("request_id", ""))
        record_agent_event(request_id=request_id, agent=node_name, status="started")
        try:
            output = fn(state)
            if node_name != "OrchestratorAgent":
                output["orchestration"]["completed_agents"].append(node_name)
            record_agent_event(
                request_id=request_id,
                agent=node_name,
                status="completed",
                elapsed_ms=elapsed_ms(started_at),
            )
            return output
        except Exception as exc:  # noqa: BLE001
            attempts += 1
            record_agent_event(
                request_id=request_id,
                agent=node_name,
                status="retrying" if attempts < 2 else "failed",
                elapsed_ms=elapsed_ms(started_at),
                error=str(exc),
            )
            if attempts >= 2:
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


def evaluate_impact_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "ImpactEvaluationAgent", impact_evaluation_agent.run)


def knowledge_base_rag_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "KnowledgeBaseRAGAgent", knowledge_base_rag_agent.run)
