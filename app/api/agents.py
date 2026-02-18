from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.graph.builder import build_graph

router = APIRouter(prefix="/agents", tags=["agents"])


class RunRequest(BaseModel):
    input: str = Field(..., description="Incident context and user request")
    service_name: str | None = Field(default=None, description="Target service name")
    raw_logs: list[str] = Field(default_factory=list, description="Optional raw logs from caller")


class RunResponse(BaseModel):
    collected_logs: str | None = None
    log_analysis: str | None = None
    impact_evaluation: str | None = None
    source_code_analysis: str | None = None
    recommendation: str


@router.post("/run", response_model=RunResponse)
def run_agents(req: RunRequest) -> RunResponse:
    graph = build_graph()
    state = {
        "messages": [{"role": "user", "content": req.input}],
        "service_name": req.service_name,
        "raw_logs": req.raw_logs,
        "next": "log_collector",
    }
    out = graph.invoke(state)
    return RunResponse(
        collected_logs=out.get("collected_logs"),
        log_analysis=out.get("log_analysis"),
        impact_evaluation=out.get("impact_evaluation"),
        source_code_analysis=out.get("source_code_analysis"),
        recommendation=out.get("recommendation") or "",
    )
