"""LangGraph-style orchestration engine."""

from langgraph.graph import END, START, StateGraph

from app.graph.nodes import (
    analyze_logs_node,
    collect_logs_node,
    evaluate_impact_node,
    recommend_node,
    source_code_analysis_node,
)
from app.graph.routing import next_after_impact
from app.state import SharedState


def build_graph():
    """Create compiled graph with router-based conditional flow."""

    graph = StateGraph(SharedState)
    graph.add_node("collect_logs", collect_logs_node)
    graph.add_node("analyze_logs", analyze_logs_node)
    graph.add_node("evaluate_impact", evaluate_impact_node)
    graph.add_node("source_code_analysis", source_code_analysis_node)
    graph.add_node("recommend", recommend_node)

    graph.add_edge(START, "collect_logs")
    graph.add_edge("collect_logs", "analyze_logs")
    graph.add_edge("analyze_logs", "evaluate_impact")
    graph.add_conditional_edges(
        "evaluate_impact",
        next_after_impact,
        {
            "source_code_analysis": "source_code_analysis",
            "recommend": "recommend",
        },
    )
    graph.add_edge("source_code_analysis", "recommend")
    graph.add_edge("recommend", END)
    return graph.compile()
