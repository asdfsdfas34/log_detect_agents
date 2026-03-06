"""Graph nodes with retry and graceful degradation."""

from collections.abc import Callable

from app.agents.anomaly_detection import AnomalyDetectionAgent
from app.agents.impact_evaluation import ImpactEvaluationAgent
from app.agents.incident_correlation import IncidentCorrelationAgent
from app.agents.knowledge_base_rag import KnowledgeBaseRAGAgent
from app.agents.log_analysis import LogAnalysisAgent
from app.agents.log_collector import LogCollectorAgent
from app.agents.orchestrator import OrchestratorAgent
from app.agents.recommendation import RecommendationAgent
from app.agents.source_code_analysis import SourceCodeAnalysisAgent
from app.state import SharedState

NodeCallable = Callable[[SharedState], SharedState]


orchestrator_agent = OrchestratorAgent()
log_collector_agent = LogCollectorAgent()
log_analysis_agent = LogAnalysisAgent()
anomaly_detection_agent = AnomalyDetectionAgent()
incident_correlation_agent = IncidentCorrelationAgent()
impact_evaluation_agent = ImpactEvaluationAgent()
source_code_analysis_agent = SourceCodeAnalysisAgent()
knowledge_base_rag_agent = KnowledgeBaseRAGAgent()
recommendation_agent = RecommendationAgent()


def _run_with_retry(state: SharedState, node_name: str, fn: NodeCallable) -> SharedState:
    """Retry one time and record failures without breaking full flow."""

    attempts = 0
    while attempts < 2:
        try:
            output = fn(state)
            if node_name != "OrchestratorAgent":
                output["orchestration"]["completed_agents"].append(node_name)
            return output
        except Exception as exc:  # noqa: BLE001
            attempts += 1
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


def incident_correlation_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "IncidentCorrelationAgent", incident_correlation_agent.run)


def evaluate_impact_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "ImpactEvaluationAgent", impact_evaluation_agent.run)


def source_code_analysis_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "SourceCodeAnalysisAgent", source_code_analysis_agent.run)


def knowledge_base_rag_node(state: SharedState) -> SharedState:
    return _run_with_retry(state, "KnowledgeBaseRAGAgent", knowledge_base_rag_agent.run)


def recommend_node(state: SharedState) -> SharedState:
    state = _run_with_retry(state, "RecommendationAgent", recommendation_agent.run)
    return knowledge_base_rag_agent.persist_final_answer(state)
