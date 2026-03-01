"""FastAPI entrypoint for 장애 예방 AI backend."""

from fastapi import FastAPI
from pydantic import BaseModel, Field

from app.config import settings
from app.graph.engine import build_graph
from app.state import Scope, SharedState, create_initial_state

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Failure Prevention AI Backend", version="0.2.0")

# 로컬 개발용: Vue dev server 주소(보통 5173 또는 8080)
origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,          # 개발 단계에서는 ["*"]도 가능(단, credentials면 안됨)
    allow_credentials=True,
    allow_methods=["*"],            # OPTIONS 포함
    allow_headers=["*"],            # Authorization 포함
)


class AnalyzeRequest(BaseModel):
    """Analyze API input schema."""

    service_name: str = Field(..., min_length=1, description="Target service name")
    goal: str = Field(default="service log anomaly investigation", description="Analysis goal")
    scope: Scope | None = Field(default=None, description="Optional detailed analysis scope")


class AnalyzeResponse(BaseModel):
    """Analyze API output schema."""

    result: SharedState


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "model": settings.openai_model, "stub_mode": str(settings.llm_stub_mode)}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    graph = build_graph()
    effective_scope: Scope = req.scope or {
        "systems": [req.service_name],
        "time_range": {"from": "", "to": ""},
        "filters": {},
    }
    effective_scope["systems"] = [req.service_name]

    initial_state = create_initial_state(goal=req.goal, scope=effective_scope)
    result = graph.invoke(initial_state)
    return AnalyzeResponse(result=result)
