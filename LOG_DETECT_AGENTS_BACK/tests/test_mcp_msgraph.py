import json

import pytest

from app.mcp.server import MCPServer


class _FakeResponse:
    def __init__(self, *, status: int = 200, payload: dict | None = None) -> None:
        self.status = status
        self._raw = json.dumps(payload or {}).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_msgraph_request_tool_calls_graph_api(monkeypatch):
    captured = {}

    def _fake_urlopen(req, timeout=0):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["auth"] = req.headers.get("Authorization")
        return _FakeResponse(payload={"value": [{"id": "u1"}]})

    monkeypatch.setattr("app.integrations.microsoft_graph.request.urlopen", _fake_urlopen)

    server = MCPServer()
    result = server.call_tool(
        "msgraph.request",
        {
            "endpoint": "/users",
            "method": "GET",
            "token": "test-token",
            "params": {"$top": 1},
        },
    )

    assert result == {"value": [{"id": "u1"}]}
    assert captured["method"] == "GET"
    assert "users" in captured["url"]
    assert "%24top=1" in captured["url"]
    assert captured["auth"] == "Bearer test-token"


def test_msgraph_request_tool_requires_token(monkeypatch):
    monkeypatch.delenv("MS_GRAPH_API_TOKEN", raising=False)
    server = MCPServer()

    with pytest.raises(ValueError):
        server.call_tool("msgraph.request", {"endpoint": "/me"})
