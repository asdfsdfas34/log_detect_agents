"""LangSmith integration and lightweight local agent-flow log buffer."""

from __future__ import annotations

import importlib
import os
from collections import deque
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from app.config import settings

_LOCAL_EVENTS: deque[dict[str, Any]] = deque(maxlen=200)


def configure_langsmith() -> None:
    """Populate LangSmith/LangChain tracing environment variables."""

    if not settings.langsmith_tracing:
        return

    os.environ.setdefault("LANGSMITH_TRACING", "true")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
    os.environ.setdefault("LANGSMITH_PROJECT", settings.langsmith_project)
    os.environ.setdefault("LANGCHAIN_PROJECT", settings.langsmith_project)
    os.environ.setdefault("LANGSMITH_ENDPOINT", settings.langsmith_endpoint)
    os.environ.setdefault("LANGCHAIN_ENDPOINT", settings.langsmith_endpoint)
    if settings.langsmith_api_key:
        os.environ.setdefault("LANGSMITH_API_KEY", settings.langsmith_api_key)
        os.environ.setdefault("LANGCHAIN_API_KEY", settings.langsmith_api_key)


def record_agent_event(
    *,
    request_id: str,
    agent: str,
    status: str,
    elapsed_ms: int | None = None,
    error: str = "",
) -> None:
    """Record an agent transition for dashboard display even without LangSmith API access."""

    _LOCAL_EVENTS.appendleft(
        {
            "id": f"local-{len(_LOCAL_EVENTS) + 1}-{datetime.now(UTC).timestamp()}",
            "request_id": request_id,
            "name": agent,
            "run_type": "chain",
            "status": status,
            "elapsed_ms": elapsed_ms,
            "error": error,
            "start_time": datetime.now(UTC).isoformat(),
            "project_name": settings.langsmith_project,
            "source": "local",
        }
    )


def start_timer() -> float:
    return perf_counter()


def elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def fetch_langsmith_runs(*, limit: int = 20) -> dict[str, Any]:
    """Fetch recent LangSmith runs and append local fallback events."""

    local_events = list(_LOCAL_EVENTS)[:limit]
    if not settings.langsmith_tracing or not settings.langsmith_api_key:
        return {
            "enabled": settings.langsmith_tracing,
            "project": settings.langsmith_project,
            "source": "local",
            "runs": local_events,
        }

    try:
        langsmith = importlib.import_module("langsmith")
        client = langsmith.Client(
            api_key=settings.langsmith_api_key,
            api_url=settings.langsmith_endpoint,
        )
        runs = []
        for run in client.list_runs(project_name=settings.langsmith_project, limit=limit):
            start_time = getattr(run, "start_time", None)
            end_time = getattr(run, "end_time", None)
            elapsed = None
            if start_time and end_time:
                elapsed = int((end_time - start_time).total_seconds() * 1000)
            runs.append(
                {
                    "id": str(getattr(run, "id", "")),
                    "request_id": "",
                    "name": str(getattr(run, "name", "")),
                    "run_type": str(getattr(run, "run_type", "")),
                    "status": "error" if getattr(run, "error", None) else "success",
                    "elapsed_ms": elapsed,
                    "error": str(getattr(run, "error", "") or ""),
                    "start_time": start_time.isoformat() if start_time else "",
                    "project_name": settings.langsmith_project,
                    "source": "langsmith",
                }
            )
        return {
            "enabled": True,
            "project": settings.langsmith_project,
            "source": "langsmith",
            "runs": runs or local_events,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "enabled": True,
            "project": settings.langsmith_project,
            "source": "local",
            "error": str(exc),
            "runs": local_events,
        }
