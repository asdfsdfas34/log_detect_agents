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

    risk = state["assessment"].get("risk_score") or 0
    anomalies = state["evidence"]["anomalies"]

    if not anomalies and risk < 30:
        state["decisions"]["assumptions"].append("low-risk early exit condition met")
        return "recommend"

    if should_run_code_analysis(state):
        if state["evidence"]["stack_traces"]:
            return "source_code_analysis"
        state["decisions"]["assumptions"].append(
            "추가 데이터 필요: risk가 높지만 stack_traces가 없어 코드 분석을 생략했습니다."
        )
        state["decisions"]["skipped_agents"].append("SourceCodeAnalysisAgent")
        return "recommend"

    state["decisions"]["skipped_agents"].append("SourceCodeAnalysisAgent")
    return "recommend"
