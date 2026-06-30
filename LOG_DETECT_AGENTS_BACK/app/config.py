"""Application configuration."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# config.py 파일 기준 경로
BASE_DIR = Path(__file__).resolve().parent  # app/
ENV_PATH = BASE_DIR.parent / ".env.dev"  # project/.env.dev

# 실제 존재 여부 확인
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=False)
else:
    print(f"⚠ .env.dev not found at: {ENV_PATH}")


def _resolve_project_path(value: str, fallback: str = "") -> str:
    raw = value.strip() or fallback
    if not raw:
        return ""
    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR.parent / path
    return str(path)


def _resolve_positive_int(value: str, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _resolve_embedding_provider(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    if normalized in {"azure", "azure_openai"}:
        return "azure_openai"
    return "openai"


@dataclass(frozen=True)
class Settings:
    """Environment-driven runtime settings."""

    openai_api_key: str
    openai_model: str
    openai_embedding_api_key: str
    openai_embedding_model: str
    openai_embedding_dimensions: int
    openai_pattern_embedding_dimensions: int
    openai_case_card_embedding_dimensions: int
    embedding_provider: str
    azure_openai_embedding_api_key: str
    azure_openai_embedding_endpoint: str
    azure_openai_embedding_api_version: str
    azure_openai_embedding_deployment: str
    sqlite_path: str
    chromadb_path: str
    log_lookback_days: int
    log_level: str
    llm_stub_mode: bool
    langsmith_tracing: bool
    langsmith_project: str
    langsmith_api_key: str
    langsmith_endpoint: str


settings = Settings(
    openai_api_key=os.getenv("OPENAI_API_KEY", ""),
    openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    openai_embedding_api_key=os.getenv("OPENAI_EMBEDDING_API_KEY", ""),
    openai_embedding_model=os.getenv(
        "OPENAI_EMBEDDING_MODEL", "text-embedding-3-large"
    ),
    openai_embedding_dimensions=_resolve_positive_int(
        os.getenv("OPENAI_EMBEDDING_DIMENSIONS", ""), 1024
    ),
    openai_pattern_embedding_dimensions=_resolve_positive_int(
        os.getenv("OPENAI_PATTERN_EMBEDDING_DIMENSIONS", ""),
        _resolve_positive_int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", ""), 1024),
    ),
    openai_case_card_embedding_dimensions=_resolve_positive_int(
        os.getenv("OPENAI_CASE_CARD_EMBEDDING_DIMENSIONS", ""),
        _resolve_positive_int(os.getenv("OPENAI_EMBEDDING_DIMENSIONS", ""), 1536),
    ),
    embedding_provider=_resolve_embedding_provider(
        os.getenv("EMBEDDING_PROVIDER", os.getenv("OPENAI_EMBEDDING_PROVIDER", "openai"))
    ),
    azure_openai_embedding_api_key=os.getenv("AZURE_OPENAI_EMBEDDING_API_KEY", ""),
    azure_openai_embedding_endpoint=os.getenv(
        "AZURE_OPENAI_EMBEDDING_ENDPOINT", os.getenv("AZURE_OPENAI_ENDPOINT", "")
    ),
    azure_openai_embedding_api_version=os.getenv(
        "AZURE_OPENAI_EMBEDDING_API_VERSION",
        os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    ),
    azure_openai_embedding_deployment=os.getenv(
        "AZURE_OPENAI_EMBEDDING_DEPLOYMENT", ""
    ),
    sqlite_path=_resolve_project_path(
        os.getenv("SQLITE_PATH", ""), os.getenv("POSTGRESQL_URL", "")
    ),
    chromadb_path=_resolve_project_path(os.getenv("CHROMADB_PATH", "./.chroma")),
    log_lookback_days=_resolve_positive_int(os.getenv("LOG_LOOKBACK_DAYS", ""), 21),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    llm_stub_mode=os.getenv("LLM_STUB_MODE", "true").lower() != "false",
    langsmith_tracing=os.getenv(
        "LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "false")
    ).lower()
    in {"1", "true", "yes", "on"},
    langsmith_project=os.getenv(
        "LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", "log-detect-agents")
    ),
    langsmith_api_key=os.getenv(
        "LANGSMITH_API_KEY", os.getenv("LANGCHAIN_API_KEY", "")
    ),
    langsmith_endpoint=os.getenv(
        "LANGSMITH_ENDPOINT",
        os.getenv("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com"),
    ),
)
