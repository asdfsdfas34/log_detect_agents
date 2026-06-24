"""LangGraph-style orchestration engine."""

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    analyze_logs_node,
    anomaly_detection_node,
    collect_logs_node,
    evaluate_impact_node,
    orchestrator_node,
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
    graph.add_node("impact_evaluation", evaluate_impact_node)

    graph.add_edge(START, "orchestrator")
    graph.add_conditional_edges(
        "orchestrator",
        route_from_orchestrator,
        {
            "LogCollectorAgent": "log_collector",
            "LogAnalysisAgent": "log_analysis",
            "AnomalyDetectionAgent": "anomaly_detection",
            "ImpactEvaluationAgent": "impact_evaluation",
            "END": END,
        },
    )

    for worker in [
        "log_collector",
        "log_analysis",
        "anomaly_detection",
        "impact_evaluation",
    ]:
        graph.add_edge(worker, "orchestrator")

    return graph.compile()
