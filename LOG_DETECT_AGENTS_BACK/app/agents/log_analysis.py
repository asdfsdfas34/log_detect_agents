"""LogAnalysisAgent implementation using deterministic MCP-backed analysis storage."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Any

from app.mcp import get_mcp_client
from app.state import SharedState
from app.suppression_config import get_suppression_config

_TOKEN_PATTERN = re.compile(r"[a-z0-9_./:-]+")
_NORMALIZATION_RULES = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}t\d{2}:\d{2}:\d{2}(?:\.\d+)?z?\b", re.I), "<timestamp>"),
    (re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds|m|minutes)\b", re.I), "<duration>"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "<ip>"),
    (re.compile(r"\b(?:request|trace|span|correlation)[_-]?id[=:][a-z0-9-]+\b", re.I), "<request_id>"),
    (re.compile(r"\buser[_-]?id[=:][a-z0-9-]+\b", re.I), "<user_id>"),
    (re.compile(r"(?<=/)\d+(?=/|\b)"), "<id>"),
    (re.compile(r"\b\d+\b"), "<number>"),
]
_ERROR_TOKENS = {"error", "exception", "fail", "failed", "failure", "critical", "timeout"}
_WARN_TOKENS = {"warn", "warning", "retry", "retried"}


class LogAnalysisAgent:
    """Analyze collected logs, classify patterns, and persist deterministic output."""

    name = "LogAnalysisAgent"

    @staticmethod
    def _known_pattern_registry() -> list[dict[str, Any]]:
        """Return known suppression patterns from config."""

        return get_suppression_config()["known_patterns"]

    def run(self, state: SharedState) -> SharedState:
        logs = state["evidence"]["normalized_logs"]
        anomalies: list[dict] = []
        suppressed_logs: list[dict] = []
        known_pattern_matches: list[dict] = []
        new_pattern_candidates: list[dict] = []
        cluster_counter: Counter[str] = Counter()

        normalized_frequencies = Counter(
            self._normalize_message(str(log.get("message", ""))) for log in logs
        )

        for log in logs:
            message = str(log.get("message", ""))
            normalized_message = self._normalize_message(message)
            level = str(log.get("level", "INFO")).upper()
            stack_trace = str(log.get("stack_trace", "") or "")
            fingerprint = self._fingerprint(normalized_message)

            match = self._match_known_pattern(
                message=message,
                normalized_message=normalized_message,
                level=level,
                stack_trace=stack_trace,
                frequency=normalized_frequencies[normalized_message],
            )

            if match:
                known_pattern_matches.append(
                    {
                        "system": log.get("system"),
                        "pattern_id": match["pattern_id"],
                        "pattern": match["pattern"],
                        "classification": match["classification"],
                        "match_result": match["match_result"],
                        "confidence": match["confidence"],
                        "matched_by": match["matched_by"],
                        "suppression": match["suppression"],
                        "fingerprint": fingerprint,
                        "message_template": normalized_message,
                        "message": message,
                    }
                )

                if match["match_result"] == "known_suppressed":
                    enriched_log = {**log, "fingerprint": fingerprint, "message_template": normalized_message}
                    suppressed_logs.append(enriched_log)
                    cluster_counter[f"suppressed:{match['classification']}"] += 1
                    continue

            is_error = self._is_error_log(level, normalized_message)
            is_warning = self._is_warning_log(level, normalized_message)

            if is_error:
                severity = self._severity(level, normalized_message, match)
                pattern = match["pattern"] if match else "error_exception"
                anomalies.append(
                    {
                        "system": log.get("system"),
                        "severity": severity,
                        "pattern": pattern,
                        "message": message,
                        "fingerprint": fingerprint,
                        "message_template": normalized_message,
                        "known_pattern_id": match.get("pattern_id") if match else None,
                        "pattern_status": match["match_result"] if match else "new_pattern_candidate",
                    }
                )
                cluster_counter[f"error:{severity}"] += 1
                if not match:
                    new_pattern_candidates.append(
                        self._new_pattern_candidate(log, normalized_message, fingerprint, "error_signal")
                    )
            elif is_warning:
                cluster_counter["warn:retry"] += 1
                if not match and normalized_frequencies[normalized_message] >= 2:
                    new_pattern_candidates.append(
                        self._new_pattern_candidate(log, normalized_message, fingerprint, "repeated_warning")
                    )
            else:
                cluster_counter["info:normal"] += 1

        state["evidence"]["anomalies"] = anomalies
        state["evidence"]["suppressed_logs"] = suppressed_logs
        state["evidence"]["known_pattern_matches"] = known_pattern_matches
        state["evidence"]["new_pattern_candidates"] = self._dedupe_by_fingerprint(
            new_pattern_candidates
        )
        state["evidence"]["clusters"] = [
            {"cluster": key, "count": value} for key, value in sorted(cluster_counter.items())
        ]

        state["decisions"]["assumptions"].append(
            "Known Pattern Registry deterministic check "
            f"match={len(known_pattern_matches)}, suppressed={len(suppressed_logs)}, "
            f"new_candidates={len(state['evidence']['new_pattern_candidates'])}"
        )

        analysis_text = self._build_analysis_summary(
            anomalies=anomalies,
            known_pattern_matches=known_pattern_matches,
            new_pattern_candidates=state["evidence"]["new_pattern_candidates"],
            suppressed_logs=suppressed_logs,
            clusters=state["evidence"]["clusters"],
        )

        target_service = (state["scope"].get("systems") or ["all"])[0]
        mcp = get_mcp_client()
        mcp.call_tool(
            "sqlite.save_log_analysis",
            {"goal": state["goal"], "service_name": target_service, "analysis": analysis_text},
        )

        state["decisions"]["agents_run"].append(self.name)
        return state

    @classmethod
    def _normalize_message(cls, message: str) -> str:
        normalized = message.strip().lower()
        for pattern, replacement in _NORMALIZATION_RULES:
            normalized = pattern.sub(replacement, normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    @staticmethod
    def _fingerprint(normalized_message: str) -> str:
        digest = hashlib.sha256(normalized_message.encode("utf-8")).hexdigest()[:12]
        return f"FP-{digest.upper()}"

    @classmethod
    def _match_known_pattern(
        cls,
        *,
        message: str,
        normalized_message: str,
        level: str,
        stack_trace: str,
        frequency: int,
    ) -> dict[str, Any] | None:
        del message
        best_match: dict[str, Any] | None = None
        best_score = 0.0
        best_reasons: list[str] = []
        stack_lower = stack_trace.lower()

        for entry in cls._known_pattern_registry():
            score = 0.0
            reasons: list[str] = []
            patterns = entry.get("patterns", [entry["pattern"]])
            normalized_patterns = [cls._normalize_message(str(pattern)) for pattern in patterns]

            if any(pattern in normalized_message for pattern in normalized_patterns):
                score += 0.45
                reasons.append("keyword")

            similarity = max(
                SequenceMatcher(None, normalized_message, pattern).ratio()
                for pattern in normalized_patterns
            )
            if similarity >= 0.86:
                score += 0.25
                reasons.append("message_similarity")

            if level in set(entry.get("level_scope", [])):
                score += 0.10
                reasons.append("level_scope")
            elif level in {"ERROR", "CRITICAL"} and entry.get("suppression"):
                score -= 0.10
                reasons.append("level_escalation")

            stack_tokens = [str(token).lower() for token in entry.get("stack_tokens", [])]
            if stack_lower and any(token in stack_lower for token in stack_tokens):
                score += 0.20
                reasons.append("stack_trace")

            if frequency >= 5 and entry.get("suppression"):
                score -= 0.15
                reasons.append("frequency_escalation")

            if score > best_score:
                best_score = score
                best_match = entry
                best_reasons = reasons

        if not best_match or best_score < 0.45:
            return None

        confidence = round(max(0.0, min(best_score, 0.99)), 2)
        suppression = bool(best_match["suppression"])
        if suppression and ("frequency_escalation" in best_reasons or confidence < 0.65):
            match_result = "known_monitor"
            suppression = False
        elif suppression:
            match_result = "known_suppressed"
        elif best_match["classification"] == "critical":
            match_result = "known_escalated"
        else:
            match_result = "known_monitor"

        return {
            "pattern_id": best_match["pattern_id"],
            "pattern": best_match["pattern"],
            "classification": best_match["classification"],
            "suppression": suppression,
            "match_result": match_result,
            "confidence": confidence,
            "matched_by": best_reasons,
        }

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(_TOKEN_PATTERN.findall(text))

    @classmethod
    def _is_error_log(cls, level: str, normalized_message: str) -> bool:
        tokens = cls._tokens(normalized_message)
        return level in {"ERROR", "CRITICAL"} or bool(tokens & _ERROR_TOKENS)

    @classmethod
    def _is_warning_log(cls, level: str, normalized_message: str) -> bool:
        tokens = cls._tokens(normalized_message)
        return level == "WARN" or bool(tokens & _WARN_TOKENS)

    @staticmethod
    def _severity(level: str, normalized_message: str, match: dict[str, Any] | None) -> str:
        if match and match["classification"] == "critical":
            return "high"
        if level in {"ERROR", "CRITICAL"} or "exception" in normalized_message:
            return "high"
        return "mid"

    @staticmethod
    def _new_pattern_candidate(
        log: dict, normalized_message: str, fingerprint: str, reason: str
    ) -> dict:
        return {
            "system": log.get("system"),
            "fingerprint": fingerprint,
            "message_template": normalized_message,
            "message": log.get("message", ""),
            "reason": reason,
            "confidence": 0.4,
            "match_result": "new_pattern_candidate",
        }

    @staticmethod
    def _dedupe_by_fingerprint(candidates: list[dict]) -> list[dict]:
        deduped: dict[str, dict] = {}
        for candidate in candidates:
            fingerprint = str(candidate.get("fingerprint", ""))
            if fingerprint not in deduped:
                deduped[fingerprint] = candidate
        return list(deduped.values())

    @staticmethod
    def _build_analysis_summary(
        *,
        anomalies: list[dict],
        known_pattern_matches: list[dict],
        new_pattern_candidates: list[dict],
        suppressed_logs: list[dict],
        clusters: list[dict],
    ) -> str:
        cluster_summary = ", ".join(
            f"{item.get('cluster')}={item.get('count')}" for item in clusters
        ) or "none"
        known_summary = ", ".join(
            f"{item.get('pattern_id')}:{item.get('match_result')}:{item.get('confidence')}"
            for item in known_pattern_matches[:5]
        ) or "none"
        new_summary = ", ".join(
            f"{item.get('fingerprint')}:{item.get('reason')}" for item in new_pattern_candidates[:5]
        ) or "none"
        return (
            "Deterministic log analysis summary\n"
            f"- anomalies={len(anomalies)}\n"
            f"- known_pattern_matches={len(known_pattern_matches)}\n"
            f"- suppressed_logs={len(suppressed_logs)}\n"
            f"- new_pattern_candidates={len(new_pattern_candidates)}\n"
            f"- clusters={cluster_summary}\n"
            f"- known_patterns={known_summary}\n"
            f"- new_candidates={new_summary}"
        )
