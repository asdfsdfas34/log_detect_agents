"""Application configuration."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Environment-driven runtime settings."""

    openai_api_key: str
    openai_model: str
    postgresql_url: str
    chromadb_path: str
    log_level: str
    llm_stub_mode: bool


settings = Settings(
    openai_api_key=os.getenv("OPENAI_API_KEY", ""),
    openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
    postgresql_url=os.getenv("POSTGRESQL_URL", ""),
    chromadb_path=os.getenv("CHROMADB_PATH", "./.chroma"),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    llm_stub_mode=os.getenv("LLM_STUB_MODE", "true").lower() != "false",
)
