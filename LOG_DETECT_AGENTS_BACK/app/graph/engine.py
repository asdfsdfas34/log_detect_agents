"""LangGraph-style orchestration engine."""

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    analyze_logs_node,
    anomaly_detection_node,
    collect_logs_node,
    evaluate_impact_node,
    incident_correlation_node,
    knowledge_base_rag_node,
    orchestrator_node,
    recommend_node,
    source_code_analysis_node,
)
from app.graph.routing import route_from_orchestrator
from app.state import SharedState


def build_graph():
    """Create compiled graph with orchestrator-based execution flow."""

    graph = StateGraph(SharedState)
    graph.add_node("orchestrator", orchestrator_node)
    graph.add_node("log_collector", collect_logs_node)
    graph.add_node("log_analysis", analyze_logs_node)
    graph.add_node("anomaly_detection", anomaly_detection_node)
    graph.add_node("incident_correlation", incident_correlation_node)
    graph.add_node("impact_evaluation", evaluate_impact_node)
    graph.add_node("source_code_analysis", source_code_analysis_node)
    graph.add_node("knowledge_base_rag", knowledge_base_rag_node)
    graph.add_node("recommendation", recommend_node)

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "LogCollectorAgent": "log_collector",
            "LogAnalysisAgent": "log_analysis",
            "AnomalyDetectionAgent": "anomaly_detection",
            "IncidentCorrelationAgent": "incident_correlation",
            "ImpactEvaluationAgent": "impact_evaluation",
            "SourceCodeAnalysisAgent": "source_code_analysis",
            "KnowledgeBaseRAGAgent": "knowledge_base_rag",
            "RecommendationAgent": "recommendation",
            "END": END,
        },
    )

    for worker in [
        "log_collector",
        "log_analysis",
        "anomaly_detection",
        "incident_correlation",
        "impact_evaluation",
        "source_code_analysis",
        "knowledge_base_rag",
        "recommendation",
    ]:
        graph.add_edge(worker, "orchestrator")

    return graph.compile()
