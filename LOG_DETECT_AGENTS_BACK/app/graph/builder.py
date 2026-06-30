from __future__ import annotations

from datetime import datetime

from langgraph.graph import END, StateGraph

from app.agents.prompts import (
    LOG_ANALYSIS_SYSTEM,
    LOG_COLLECTOR_SYSTEM,
    RECOMMENDATION_SYSTEM,
)
from app.db.chroma_store import find_related_analyses, save_analysis_document
from app.db.sqlite_store import fetch_recent_logs
from app.llm.openai_client import generate_text
from app.state import AgentState


def _combine_logs(user_msg: str, logs: list[str]) -> str:
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
    state["next"] = "recommendation"
    return state


def _recommendation(state: AgentState) -> AgentState:
    analysis = state.get("log_analysis") or ""

    recommendation = generate_text(
        messages=[
            {"role": "system", "content": RECOMMENDATION_SYSTEM},
            {
                "role": "user",
                "content": (
                    "로그 분석 결과를 기반으로 권고안을 한국어로 작성하세요.\n\n"
                    f"Log analysis:\n{analysis}"
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
            f"Log analysis:\n{analysis}\n\nRecommendation:\n{recommendation}"
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
        {"recommendation": "recommendation", "end": END},
    )
    g.add_conditional_edges(
        "recommendation",
        _route,
        {"end": END},
    )

    return g.compile()
