from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI

from app.api.agents import router as agents_router

load_dotenv()

app = FastAPI(title="LangGraph Multi-Agent API", version="0.1.0")

app.include_router(agents_router)


@app.get("/health")
def health():
    return {"status": "ok", "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini")}
