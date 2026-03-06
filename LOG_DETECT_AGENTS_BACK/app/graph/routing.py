"""Routing rules for orchestrator-controlled graph."""

from app.state import SharedState


def route_from_orchestrator(state: SharedState) -> str:
    """Return next node name chosen by orchestrator."""

    return state["orchestration"].get("next_agent") or "END"
