"""Application configuration."""

import os
from dataclasses import dataclass

from pathlib import Path
from dotenv import load_dotenv

# config.py 파일 기준 경로
BASE_DIR = Path(__file__).resolve().parent        # app/
ENV_PATH = BASE_DIR.parent / ".env.dev"          # project/.env.dev

# 실제 존재 여부 확인
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)
else:
    print(f"⚠ .env.dev not found at: {ENV_PATH}")

@dataclass(frozen=True)
class Settings:
    """Environment-driven runtime settings."""

    openai_api_key: str
    openai_model: str
    sqlite_path: str
    chromadb_path: str
    log_level: str
    llm_stub_mode: bool
    langsmith_tracing: bool
    langsmith_project: str
    langsmith_api_key: str
    langsmith_endpoint: str


settings = Settings(
    openai_api_key=os.getenv("OPENAI_API_KEY", ""),
    openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    sqlite_path=(os.getenv("SQLITE_PATH", "").strip() or os.getenv("POSTGRESQL_URL", "")),
    chromadb_path=os.getenv("CHROMADB_PATH", "./.chroma"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    llm_stub_mode=os.getenv("LLM_STUB_MODE", "true").lower() != "false",
    langsmith_tracing=os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "false")).lower()
    in {"1", "true", "yes", "on"},
    langsmith_project=os.getenv("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", "log-detect-agents")),
    langsmith_api_key=os.getenv("LANGSMITH_API_KEY", os.getenv("LANGCHAIN_API_KEY", "")),
    langsmith_endpoint=os.getenv("LANGSMITH_ENDPOINT", os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")),
)
