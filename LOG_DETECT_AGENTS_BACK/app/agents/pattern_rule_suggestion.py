"""Pattern normalization rule suggestion agent."""

from __future__ import annotations

import re
from dataclasses import dataclass


EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
REQUEST_ID_RE = re.compile(
    r"\s*\b(?:request|trace|span|correlation)[_-]?id\s*[:=]\s*[A-Za-z0-9-]+\b",
    re.IGNORECASE,
)
KEY_VALUE_NUMBER_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)(\s*[:=]\s*)\d+\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
HASH_LIKE_RE = re.compile(r"\b(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{10,}\b")
NUMBER_RE = re.compile(r"\b\d+\b")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class PatternRuleProposal:
    """A proposed deterministic normalization rule."""

    name: str
    match_regex: str
    template: str
    confidence: str
    reason: str
    sample_before: str
    sample_after: str


class PatternRuleSuggestionAgent:
    """Suggest regex-backed normalization rules from example log messages."""

    name = "PatternRuleSuggestionAgent"

    def propose(self, *, message: str, cluster: str = "") -> PatternRuleProposal:
        sample = WHITESPACE_RE.sub(" ", message or "").strip()
        template = self._template(sample)
        match_regex = self._regex_from_template(template)
        normalized_cluster = cluster or self._name_from_template(template)
        return PatternRuleProposal(
            name=normalized_cluster[:120] or "Pattern normalization rule",
            match_regex=match_regex,
            template=template,
            confidence="high" if template != sample else "mid",
            reason=(
                "동적 email, key-value 숫자, request/trace id 후보를 일반화한 "
                "정규화 룰입니다. 승인 후 동일 구조 로그는 같은 template으로 묶입니다."
            ),
            sample_before=sample,
            sample_after=template,
        )

    @staticmethod
    def _template(message: str) -> str:
        text = REQUEST_ID_RE.sub("", message)
        text = EMAIL_RE.sub("<email>", text)
        text = UUID_RE.sub("<id>", text)
        text = KEY_VALUE_NUMBER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}<number>", text)
        text = HASH_LIKE_RE.sub("<id>", text)
        text = NUMBER_RE.sub("<number>", text)
        return WHITESPACE_RE.sub(" ", text).strip(" ,")

    @staticmethod
    def _regex_from_template(template: str) -> str:
        escaped = re.escape(template)
        escaped = escaped.replace(r"<email>", r"[^,\s]+")
        escaped = escaped.replace(r"<number>", r"\d+")
        escaped = escaped.replace(r"<id>", r"[A-Za-z0-9-]+")
        escaped = re.sub(r"\\\s+", r"\\s+", escaped)
        request_suffix = (
            r"(?:\s+\b(?:request|trace|span|correlation)[_-]?id\s*[:=]\s*"
            r"[A-Za-z0-9-]+)?"
        )
        return f"^{escaped}{request_suffix}$"

    @staticmethod
    def _name_from_template(template: str) -> str:
        return template.split(".")[0] if "." in template else template[:80]
