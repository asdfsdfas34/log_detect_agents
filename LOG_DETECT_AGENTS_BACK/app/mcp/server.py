"""Single MCP server that exposes SQLite, ChromaDB, and OpenAI tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.db.chroma_store import find_related_analyses, save_analysis_document
from app.db.sqlite_store import (
    fetch_latest_log_analyses,
    fetch_recent_log_entries,
    fetch_recent_logs,
    save_impact_evaluation,
    save_log_analysis,
)
from app.llm.openai_client import generate_text

ToolHandler = Callable[[dict[str, Any]], Any]


class MCPServer:
    """In-process MCP server with a single tool registry."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolHandler] = {
            "sqlite.fetch_recent_logs": self._sqlite_fetch_recent_logs,
            "sqlite.fetch_recent_log_entries": self._sqlite_fetch_recent_log_entries,
            "sqlite.save_log_analysis": self._sqlite_save_log_analysis,
            "sqlite.fetch_latest_log_analyses": self._sqlite_fetch_latest_log_analyses,
            "sqlite.save_impact_evaluation": self._sqlite_save_impact_evaluation,
            "chromadb.save_analysis_document": self._chromadb_save_analysis_document,
            "chromadb.find_related_analyses": self._chromadb_find_related_analyses,
            "openai.generate_text": self._openai_generate_text,
        }

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        if tool_name not in self._tools:
            raise ValueError(f"Unknown MCP tool: {tool_name}")
        return self._tools[tool_name](arguments or {})

    @staticmethod
    def _sqlite_fetch_recent_logs(arguments: dict[str, Any]) -> list[str]:
        return fetch_recent_logs(
            service_name=arguments.get("service_name"),
            limit=int(arguments.get("limit", 20)),
        )

    @staticmethod
    def _sqlite_fetch_recent_log_entries(arguments: dict[str, Any]) -> list[dict[str, Any]]:
        service_names = arguments.get("service_names")
        return fetch_recent_log_entries(
            service_names=service_names if isinstance(service_names, list) else None,
            limit=int(arguments.get("limit", 200)),
        )

    @staticmethod
    def _sqlite_save_log_analysis(arguments: dict[str, Any]) -> None:
        save_log_analysis(
            goal=str(arguments.get("goal", "")),
            service_name=str(arguments.get("service_name", "all")),
            analysis=str(arguments.get("analysis", "")),
        )

    @staticmethod
    def _sqlite_fetch_latest_log_analyses(arguments: dict[str, Any]) -> list[dict[str, str]]:
        service_names = arguments.get("service_names")
        return fetch_latest_log_analyses(
            service_names=service_names if isinstance(service_names, list) else None,
            limit=int(arguments.get("limit", 20)),
        )

    @staticmethod
    def _sqlite_save_impact_evaluation(arguments: dict[str, Any]) -> None:
        save_impact_evaluation(
            service_name=str(arguments.get("service_name", "all")),
            risk_score=int(arguments.get("risk_score", 0)),
            confidence=str(arguments.get("confidence", "low")),
            rationale=str(arguments.get("rationale", "")),
        )

    @staticmethod
    def _chromadb_save_analysis_document(arguments: dict[str, Any]) -> None:
        save_analysis_document(
            doc_id=str(arguments.get("doc_id", "")),
            text=str(arguments.get("text", "")),
        )

    @staticmethod
    def _chromadb_find_related_analyses(arguments: dict[str, Any]) -> list[str]:
        return find_related_analyses(
            query=str(arguments.get("query", "")),
            n_results=int(arguments.get("n_results", 3)),
        )

    @staticmethod
    def _openai_generate_text(arguments: dict[str, Any]) -> str:
        messages = arguments.get("messages")
        return generate_text(
            messages=messages if isinstance(messages, list) else [],
            model=arguments.get("model"),
            temperature=float(arguments.get("temperature", 0.2)),
        )


_SINGLETON_SERVER = MCPServer()


def get_mcp_server() -> MCPServer:
    return _SINGLETON_SERVER
