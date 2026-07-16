"""MCP client used by agents to call server tools."""

from __future__ import annotations

from typing import Any

from app.mcp.server import get_mcp_server
from app.reasoning_events import (
    current_reasoning_agent,
    current_reasoning_state,
    record_reasoning_event,
    summarize_tool_result,
)


class MCPClient:
    """Thin client wrapper for MCP tool calls."""

    def __init__(self) -> None:
        self._server = get_mcp_server()

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        safe_arguments = arguments or {}
        state = current_reasoning_state()
        if state is not None:
            record_reasoning_event(
                state,
                kind="tool_call",
                agent=current_reasoning_agent(),
                status="running",
                title=f"MCP Tool Call: {tool_name}",
                detail=_tool_input_summary(safe_arguments),
                metadata={"tool_name": tool_name, "argument_keys": sorted(safe_arguments)},
            )
        try:
            result = self._server.call_tool(tool_name, safe_arguments)
        except Exception as exc:
            if state is not None:
                record_reasoning_event(
                    state,
                    kind="tool_call",
                    agent=current_reasoning_agent(),
                    status="failed",
                    title=f"MCP Tool Call 실패: {tool_name}",
                    detail=f"{type(exc).__name__}: 도구 실행에 실패했습니다.",
                    metadata={"tool_name": tool_name},
                )
            raise
        if state is not None:
            record_reasoning_event(
                state,
                kind="tool_call",
                agent=current_reasoning_agent(),
                status="completed",
                title=f"MCP Tool Call 완료: {tool_name}",
                detail=summarize_tool_result(result),
                metadata={"tool_name": tool_name},
            )
        return result


def _tool_input_summary(arguments: dict[str, Any]) -> str:
    if not arguments:
        return "입력 필드 없음"
    return f"입력 필드: {', '.join(sorted(arguments))}"


_SINGLETON_CLIENT = MCPClient()


def get_mcp_client() -> MCPClient:
    return _SINGLETON_CLIENT
