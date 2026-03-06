"""KnowledgeBaseRAGAgent implementation."""

import json

from app.mcp import get_mcp_client
from app.state import SharedState


class KnowledgeBaseRAGAgent:
    """Retrieve and (optionally) persist analysis context via ChromaDB."""

    name = "KnowledgeBaseRAGAgent"

    def run(self, state: SharedState) -> SharedState:
        mcp = get_mcp_client()
        query = state["goal"]
        related = mcp.call_tool(
            "chromadb.find_related_analyses",
            {"query": query, "n_results": 3},
        )
        state["rag"]["related_knowledge"] = related
        state["decisions"]["agents_run"].append(self.name)
        return state

    def persist_final_answer(self, state: SharedState) -> SharedState:
        if not state["preferences"].get("save_to_chromadb", False):
            state["rag"]["saved_to_chromadb"] = False
            return state

        final_answer = state["final"].get("generated_answer")
        if not final_answer:
            state["rag"]["saved_to_chromadb"] = False
            return state

        mcp = get_mcp_client()
        payload = {
            "goal": state["goal"],
            "systems": state["scope"].get("systems", []),
            "risk_score": state["assessment"].get("risk_score"),
            "generated_answer": final_answer,
        }
        mcp.call_tool(
            "chromadb.save_analysis_document",
            {
                "doc_id": f"final:{state['request_id']}",
                "text": json.dumps(payload, ensure_ascii=False),
            },
        )
        state["rag"]["saved_to_chromadb"] = True
        return state
