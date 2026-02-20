"""FastAPI entrypoint for 장애 예방 AI backend."""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.engine import build_graph
from app.state import Scope, SharedState, create_initial_state

app = FastAPI(title="Failure Prevention AI Backend", version="0.2.0")


class AnalyzeRequest(BaseModel):
    """Analyze API input schema."""

    goal: str = Field(..., description="Analysis goal")
    scope: Scope


class AnalyzeResponse(BaseModel):
    """Analyze API output schema."""

    result: SharedState


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.openai_model, "stub_mode": str(settings.llm_stub_mode)}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    graph = build_graph()
    initial_state = create_initial_state(goal=req.goal, scope=req.scope)
    result = graph.invoke(initial_state)
    return AnalyzeResponse(result=result)
