from __future__ import annotations

from datetime import datetime
from typing import List

from langgraph.graph import StateGraph, END

from app.agents.prompts import (
    IMPACT_EVALUATION_SYSTEM,
    LOG_ANALYSIS_SYSTEM,
    LOG_COLLECTOR_SYSTEM,
    RECOMMENDATION_SYSTEM,
    SOURCE_CODE_ANALYSIS_SYSTEM,
)
from app.db.chroma_store import find_related_analyses, save_analysis_document
from app.db.sqlite_store import fetch_recent_logs
from app.llm.openai_client import generate_text
from app.state import AgentState


def _combine_logs(user_msg: str, logs: List[str]) -> str:
    if not logs:
        return user_msg
    return f"{user_msg}\n\n[RECENT_LOGS]\n" + "\n".join(logs)


def _log_collector(state: AgentState) -> AgentState:
    user_msg = state["messages"][-1]["content"]
    service_name = state.get("service_name")
    raw_logs = state.get("raw_logs") or fetch_recent_logs(service_name=service_name, limit=20)
    combined = _combine_logs(user_msg, raw_logs)
    collected_logs = generate_text(
        messages=[
            {"role": "system", "content": LOG_COLLECTOR_SYSTEM},
            {"role": "user", "content": combined},
        ],
        temperature=0.2,
    )
    state["collected_logs"] = collected_logs
    state["next"] = "log_analysis"
    return state


def _log_analysis(state: AgentState) -> AgentState:
    collected_logs = state.get("collected_logs") or state["messages"][-1]["content"]
    related = find_related_analyses(query=collected_logs, n_results=3)
    related_context = "\n\n[RELATED_INCIDENTS]\n" + "\n".join(related) if related else ""

    analysis = generate_text(
        messages=[
            {"role": "system", "content": LOG_ANALYSIS_SYSTEM},
            {"role": "user", "content": f"{collected_logs}{related_context}"},
        ],
        temperature=0.2,
    )
    state["log_analysis"] = analysis
    state["next"] = "impact_evaluation"
    return state


def _impact_evaluation(state: AgentState) -> AgentState:
    analysis = state.get("log_analysis") or ""
    impact = generate_text(
        messages=[
            {"role": "system", "content": IMPACT_EVALUATION_SYSTEM},
            {"role": "user", "content": analysis},
        ],
        temperature=0.1,
    )
    state["impact_evaluation"] = impact
    state["next"] = "source_code_analysis"
    return state


def _source_code_analysis(state: AgentState) -> AgentState:
    user_msg = state["messages"][-1]["content"]
    analysis = state.get("log_analysis") or ""
    impact = state.get("impact_evaluation") or ""

    code_analysis = generate_text(
        messages=[
            {"role": "system", "content": SOURCE_CODE_ANALYSIS_SYSTEM},
            {
                "role": "user",
                "content": f"User request:\n{user_msg}\n\nLog analysis:\n{analysis}\n\nImpact:\n{impact}",
            },
        ],
        temperature=0.1,
    )
    state["source_code_analysis"] = code_analysis
    state["next"] = "recommendation"
    return state


def _recommendation(state: AgentState) -> AgentState:
    collected_logs = state.get("collected_logs") or ""
    analysis = state.get("log_analysis") or ""
    impact = state.get("impact_evaluation") or ""
    code_analysis = state.get("source_code_analysis") or ""

    recommendation = generate_text(
        messages=[
            {"role": "system", "content": RECOMMENDATION_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Collected logs:\n{collected_logs}\n\n"
                    f"Log analysis:\n{analysis}\n\n"
                    f"Impact evaluation:\n{impact}\n\n"
                    f"Source code analysis:\n{code_analysis}"
                ),
            },
        ],
        temperature=0.1,
    )
    state["recommendation"] = recommendation

    doc_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    save_analysis_document(
        doc_id=doc_id,
        text=(
            f"Log analysis:\n{analysis}\n\nImpact evaluation:\n{impact}\n\n"
            f"Source code analysis:\n{code_analysis}\n\nRecommendation:\n{recommendation}"
        ),
    )
    state["next"] = "end"
    return state


def _route(state: AgentState) -> str:
    return state.get("next", "log_collector")


def build_graph():
    g = StateGraph(AgentState)

    g.add_node("log_collector", _log_collector)
    g.add_node("log_analysis", _log_analysis)
    g.add_node("impact_evaluation", _impact_evaluation)
    g.add_node("source_code_analysis", _source_code_analysis)
    g.add_node("recommendation", _recommendation)

    g.set_entry_point("log_collector")

    g.add_conditional_edges(
        "log_collector",
        _route,
        {"log_analysis": "log_analysis", "end": END},
    )
    g.add_conditional_edges(
        "log_analysis",
        _route,
        {"impact_evaluation": "impact_evaluation", "end": END},
    )
    g.add_conditional_edges(
        "impact_evaluation",
        _route,
        {"source_code_analysis": "source_code_analysis", "end": END},
    )
    g.add_conditional_edges(
        "source_code_analysis",
        _route,
        {"recommendation": "recommendation", "end": END},
    )
    g.add_conditional_edges(
        "recommendation",
        _route,
        {"end": END},
    )

    return g.compile()
