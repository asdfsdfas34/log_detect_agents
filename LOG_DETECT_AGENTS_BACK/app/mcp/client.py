"""MCP client used by agents to call server tools."""

from __future__ import annotations

from typing import Any

from app.mcp.server import get_mcp_server


class MCPClient:
    """Thin client wrapper for MCP tool calls."""

    def __init__(self) -> None:
        self._server = get_mcp_server()

    def call_tool(self, tool_name: str, arguments: dict[str, Any] | None = None) -> Any:
        return self._server.call_tool(tool_name, arguments or {})


_SINGLETON_CLIENT = MCPClient()


def get_mcp_client() -> MCPClient:
    return _SINGLETON_CLIENT
