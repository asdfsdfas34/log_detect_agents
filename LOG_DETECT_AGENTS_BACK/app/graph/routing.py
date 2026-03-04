"""Routing rules for graph orchestration."""

from app.state import SharedState

SENSITIVE_KEYWORDS = ["auth", "payment", "결제", "인증", "data loss", "유출", "개인정보"]


def should_run_code_analysis(state: SharedState) -> bool:
    """Evaluate router condition for source code analysis."""

    risk = state["assessment"].get("risk_score") or 0
    has_high = any(a.get("severity") == "high" for a in state["evidence"]["anomalies"])
    text_blob = " ".join(
        [
            state.get("goal", ""),
            " ".join(state["scope"].get("systems", [])),
            str(state["scope"].get("filters", {})),
        ]
    ).lower()
    has_keyword = any(k.lower() in text_blob for k in SENSITIVE_KEYWORDS)
    return risk >= 70 or has_high or has_keyword


def next_after_impact(state: SharedState) -> str:
    """Route from impact evaluation to next node."""

    state["decisions"]["assumptions"].append("요청 정책에 따라 source_code_analysis 단계를 항상 생략합니다.")
    if "SourceCodeAnalysisAgent" not in state["decisions"]["skipped_agents"]:
        state["decisions"]["skipped_agents"].append("SourceCodeAnalysisAgent")
    return "recommend"
