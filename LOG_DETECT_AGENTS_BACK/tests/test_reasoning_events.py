from typing import Any

from app.mcp.client import MCPClient
from app.reasoning_events import reasoning_state
from app.state import create_initial_state


class _FakeMCPServer:
    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> list[dict[str, str]]:
        assert tool_name == "sqlite.fetch_recent_logs"
        assert arguments["service_name"] == "secret-service"
        return [{"message": "sensitive log"}]


def test_mcp_client_records_safe_high_level_tool_events() -> None:
    state = create_initial_state(
        goal="test",
        scope={"systems": ["checkout"], "time_range": {}, "filters": {}},
        request_id="req-reasoning",
    )
    client = MCPClient()
    client._server = _FakeMCPServer()

    with reasoning_state(state, agent_name="LogCollectorAgent"):
        result = client.call_tool(
            "sqlite.fetch_recent_logs",
            {"service_name": "secret-service", "limit": 10},
        )

    assert result == [{"message": "sensitive log"}]
    events = state["evidence"]["agent_reasoning_events"]
    assert [event["status"] for event in events] == ["running", "completed"]
    assert all(event["kind"] == "tool_call" for event in events)
    assert all(event["agent_name"] == "LogCollectorAgent" for event in events)
    rendered = str(events)
    assert "secret-service" not in rendered
    assert "sensitive log" not in rendered
    assert "service_name" in rendered
