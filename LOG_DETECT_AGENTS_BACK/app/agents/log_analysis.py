"""LogAnalysisAgent implementation using OpenAI + SQLite persistence."""

from collections import Counter

from app.db.sqlite_store import save_log_analysis
from app.llm.openai_client import generate_text
from app.state import SharedState


class LogAnalysisAgent:
    """Analyze collected logs and persist analysis output."""

    name = "LogAnalysisAgent"

    def run(self, state: SharedState) -> SharedState:
        logs = state["evidence"]["normalized_logs"]
        anomalies: list[dict] = []
        cluster_counter: Counter[str] = Counter()

        for log in logs:
            message = str(log.get("message", ""))
            msg = message.lower()
            level = str(log.get("level", "INFO")).upper()

            if level == "ERROR" or "error" in msg or "exception" in msg or "fail" in msg:
                severity = "high" if ("exception" in msg or "critical" in msg or level == "ERROR") else "mid"
                anomalies.append(
                    {
                        "system": log.get("system"),
                        "severity": severity,
                        "pattern": "error_exception",
                        "message": message,
                    }
                )
                cluster_counter[f"error:{severity}"] += 1
            elif level == "WARN" or "warn" in msg or "retry" in msg:
                cluster_counter["warn:retry"] += 1
            else:
                cluster_counter["info:normal"] += 1

        log_lines = [
            f"[{item.get('timestamp')}] {item.get('system')} {item.get('level')} {item.get('message')}"
            for item in logs[:80]
        ]
        prompt = (
            "다음 운영 로그를 보고 장애 징후를 분석해 주세요.\n"
            "반드시 다음 항목을 포함해 한국어로 작성하세요: 주요 원인 추정, 위험 신호, 즉시 조치.\n\n"
            f"로그:\n{chr(10).join(log_lines)}"
        )
        try:
            analysis_text = generate_text(
                messages=[
                    {"role": "system", "content": "당신은 SRE 로그 분석 전문가입니다."},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.1,
            )
        except Exception as exc:  # noqa: BLE001
            analysis_text = (
                "OpenAI 분석 호출 실패로 규칙 기반 요약으로 대체되었습니다. "
                f"error={exc}; anomalies={len(anomalies)}"
            )
            state["decisions"]["assumptions"].append("OpenAI API 호출 실패로 fallback 분석을 사용했습니다.")

        state["evidence"]["anomalies"] = anomalies
        state["evidence"]["clusters"] = [
            {"cluster": key, "count": value} for key, value in sorted(cluster_counter.items())
        ]

        target_service = (state["scope"].get("systems") or ["all"])[0]
        save_log_analysis(goal=state["goal"], service_name=target_service, analysis=analysis_text)

        state["decisions"]["agents_run"].append(self.name)
        return state
