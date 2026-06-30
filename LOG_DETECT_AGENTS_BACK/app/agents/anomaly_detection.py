"""AnomalyDetectionAgent implementation."""

from collections import Counter
import re

from app.state import SharedState
from app.suppression_config import get_suppression_config

_NUMBER_PATTERN = re.compile(r"\b\d+\b")
_UUID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.I,
)


class AnomalyDetectionAgent:
    """Detect anomalies from pattern presence, increase, decrease, and absence."""

    name = "AnomalyDetectionAgent"

    def run(self, state: SharedState) -> SharedState:
        logs = state["evidence"]["normalized_logs"]
        suppressed_logs = state["evidence"].get("suppressed_logs", [])
        key_fields = get_suppression_config()["anomaly_detection"]["suppressed_key_fields"]
        suppressed_keys = {
            tuple(str(item.get(field)) for field in key_fields) for item in suppressed_logs
        }
        filtered_logs = [
            log
            for log in logs
            if tuple(str(log.get(field)) for field in key_fields) not in suppressed_keys
        ]

        if not logs:
            state["evidence"]["anomalies"] = [
                {
                    "system": (state["scope"].get("systems") or ["unknown"])[0],
                    "severity": "mid",
                    "pattern": "pattern_absence",
                    "anomaly_type": "ABSENCE",
                    "message": "분석 대상 로그 패턴이 관측되지 않았습니다.",
                }
            ]
            state["metrics"]["anomaly_score"] = 1.0
            state["decisions"]["agents_run"].append(self.name)
            return state

        if not filtered_logs:
            state["metrics"]["anomaly_score"] = 0.0
            state["decisions"]["assumptions"].append(
                "suppression 적용 후 분석할 로그 패턴이 없어 anomaly를 생성하지 않았습니다."
            )
            state["decisions"]["agents_run"].append(self.name)
            return state

        pattern_counts: Counter[tuple[str, str, str]] = Counter(
            (
                str(log.get("system") or "unknown"),
                str(log.get("level", "INFO")).upper(),
                self._normalize_pattern(str(log.get("message", ""))),
            )
            for log in filtered_logs
        )
        pattern_events = []

        for (system, level, pattern), count in pattern_counts.items():
            if level in {"ERROR", "WARN", "WARNING"} and count >= 2:
                severity = "high" if level == "ERROR" else "mid"
                pattern_events.append(
                    {
                        "system": system,
                        "severity": severity,
                        "pattern": pattern,
                        "anomaly_type": "INCREASE",
                        "message": f"동일 {level} 패턴이 {count}회 관측되었습니다.",
                        "metric": {"current_count": count},
                    }
                )

        for cluster in state["evidence"].get("clusters", []):
            current = self._optional_number(cluster.get("current_count", cluster.get("count")))
            baseline = self._optional_number(cluster.get("baseline_count"))
            if baseline is None or current is None or baseline < 2:
                continue
            if current <= baseline * 0.5:
                pattern_events.append(
                    {
                        "system": cluster.get("system", (state["scope"].get("systems") or ["unknown"])[0]),
                        "severity": "mid",
                        "pattern": str(cluster.get("cluster") or cluster.get("pattern") or "pattern_decrease"),
                        "anomaly_type": "DECREASE",
                        "message": "기준선 대비 패턴 발생량이 감소했습니다.",
                        "metric": {"current_count": current, "baseline_count": baseline},
                    }
                )

        for candidate in state["evidence"].get("new_pattern_candidates", []):
            pattern_events.append(
                {
                    "system": candidate.get("system", (state["scope"].get("systems") or ["unknown"])[0]),
                    "severity": "high",
                    "pattern": candidate.get("fingerprint") or candidate.get("message_template") or "new_pattern",
                    "anomaly_type": "PRESENCE",
                    "message": candidate.get("message") or "신규 패턴이 관측되었습니다.",
                }
            )

        state["evidence"]["anomalies"] = self._dedupe_events(pattern_events)
        state["metrics"]["anomaly_score"] = float(len(state["evidence"]["anomalies"]))
        state["decisions"]["assumptions"].append(
            "AnomalyDetectionAgent는 점수 임계값 대신 패턴 증가/감소/부재/신규 관측 기준으로 판단했습니다."
        )

        state["decisions"]["agents_run"].append(self.name)
        return state

    @staticmethod
    def _normalize_pattern(message: str) -> str:
        normalized = _UUID_PATTERN.sub("<uuid>", message.strip().lower())
        normalized = _NUMBER_PATTERN.sub("<number>", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _optional_number(value: object) -> float | None:
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _dedupe_events(events: list[dict]) -> list[dict]:
        seen = set()
        deduped = []
        for event in events:
            key = (
                event.get("system"),
                event.get("pattern"),
                event.get("anomaly_type"),
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(event)
        return deduped
