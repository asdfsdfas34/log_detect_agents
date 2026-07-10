import pytest


@pytest.fixture(autouse=True)
def disable_pattern_reason_llm_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PATTERN_REASON_LLM_ENABLED", "false")
