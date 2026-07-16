"""MCP client used by agents to call server tools."""

from __future__ import annotations

from time import perf_counter
from typing import Any

from app.mcp.server import get_mcp_server
from app.reasoning_events import (
    current_reasoning_agent,
    current_reasoning_state,
    record_reasoning_event,
    summarize_tool_result,
)
from app.trace_events import (
    next_trace_span_index,
    redact_error,
    tool_input_summary,
)
from app.trace_events import (
    summarize_tool_result as summarize_tool_result_struct,
)


class MCPClient:
    """Thin client wrapper for MCP tool calls."""

    def __init__(self) -> None:
        self._server = get_mcp_server()

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        safe_arguments = arguments or {}
        state = current_reasoning_state()
        agent = current_reasoning_agent()
        input_summary = tool_input_summary(safe_arguments)
        span_id: str | None = None
        started_at = perf_counter()
        if state is not None:
            span_index = next_trace_span_index(state, f"{state.get('request_id', '')}:tool:")
            span_id = f"{state.get('request_id', '')}:tool:{span_index}"
            record_reasoning_event(
                state,
                kind="tool_call",
                agent=agent,
                status="running",
                title=f"MCP Tool Call: {tool_name}",
                detail=_tool_input_summary(safe_arguments),
                metadata={
                    "tool_name": tool_name,
                    "argument_keys": sorted(safe_arguments),
                    "span_id": span_id,
                    "input_summary": input_summary,
                },
            )
        try:
            result = self._server.call_tool(tool_name, safe_arguments)
        except Exception as exc:
            if state is not None:
                record_reasoning_event(
                    state,
                    kind="tool_call",
                    agent=agent,
                    status="failed",
                    title=f"MCP Tool Call 실패: {tool_name}",
                    detail=f"{type(exc).__name__}: 도구 실행에 실패했습니다.",
                    metadata={
                        "tool_name": tool_name,
                        "span_id": span_id,
                        "duration_ms": int((perf_counter() - started_at) * 1000),
                        "input_summary": input_summary,
                        "error": redact_error(exc),
                    },
                )
            raise
        if state is not None:
            record_reasoning_event(
                state,
                kind="tool_call",
                agent=agent,
                status="completed",
                title=f"MCP Tool Call 완료: {tool_name}",
                detail=summarize_tool_result(result),
                metadata={
                    "tool_name": tool_name,
                    "span_id": span_id,
                    "duration_ms": int((perf_counter() - started_at) * 1000),
                    "input_summary": input_summary,
                    "output_summary": summarize_tool_result_struct(result),
                },
            )
        return result


def _tool_input_summary(arguments: dict[str, Any]) -> str:
    if not arguments:
        return "입력 필드 없음"
    return f"입력 필드: {', '.join(sorted(arguments))}"


_SINGLETON_CLIENT = MCPClient()


def get_mcp_client() -> MCPClient:
    return _SINGLETON_CLIENT
