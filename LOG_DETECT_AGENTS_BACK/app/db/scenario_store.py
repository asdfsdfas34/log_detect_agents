"""Scenario database pipeline for log fingerprinting, detection, risk, and knowledge reuse."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from app.db.chroma_store import (
    delete_pattern_clusters,
    find_similar_analysis_documents,
    find_similar_analysis_documents_batch,
    find_similar_pattern_clusters,
    find_similar_pattern_clusters_batch,
    save_analysis_document,
    save_pattern_clusters,
)
from app.db.sqlite_store import _resolve_db_path

NUMERIC_RE = re.compile(r"\b\d+\b")
EXCEL_NEWLINE_RE = re.compile(r"_x000D_", re.IGNORECASE)
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
URL_RE = re.compile(r"https?://[^\s]+", re.IGNORECASE)
DATE_TIME_RE = re.compile(
    r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ T]\d{1,2}:\d{2}:\d{2}(?:\.\d+)?)?\b"
)
KOREAN_TIME_RE = re.compile(r"\b(?:오전|오후)\s+\d{1,2}:\d{2}:\d{2}\b")
HEX_ERROR_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
HASH_LIKE_RE = re.compile(r"\b(?=[A-Fa-f0-9]*\d)[A-Fa-f0-9]{16,}\b")
COMPILER_GENERATED_MEMBER_RE = re.compile(r"\b([<>A-Za-z_][\w<>]+)__\d+\b")
CS_LINE_RE = re.compile(r"(:줄\s*)\d+")
ANONYMOUS_LINE_RE = re.compile(r"(<anonymous>:)\d+:\d+")
WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:\\[^\s\r\n]+")
JSON_STRING_VALUE_RE = re.compile(r'(:\s*)"([^"\\]*(?:\\.[^"\\]*)*)"')
JSON_LITERAL_VALUE_RE = re.compile(
    r"(:\s*)(-?\d+(?:\.\d+)?|true|false|null)(?=\s*[,}])",
    re.IGNORECASE,
)
QUOTED_VOLATILE_RE = re.compile(r'"(?=[^"]*\d)[A-Za-z0-9_.:/\\-]{2,}"')
ASSIGNED_VALUE_RE = re.compile(
    r"(\b[A-Za-z_][\w.-]*\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
CANDIDATE_KEY_VALUE_RE = re.compile(
    r"(\b[A-Za-z_][\w.-]*\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
SEMANTIC_VALUE_RE = re.compile(
    r"\b(JobName|functionName)\s*:\s*([^\r\n]+)", re.IGNORECASE
)
URL_FIELD_RE = re.compile(r"\b(AbsoluteUri)\s*:\s*([^\s\r\n]+)", re.IGNORECASE)
IDENTIFIER_KEY_VALUE_RE = re.compile(
    r"(\b[A-Za-z_][\w.-]*(?:ID|Id|Status|Code|No|Number|Seq|Date|Time|Token|Key|"
    r"GUID|UUID)\b\s+)(?![:=])([^\s,;}\]]+)",
)
KOREAN_HONORIFIC_NUMBER_RE = re.compile(r"(?<=\S)\d+(?=님)")
LEADING_LIST_MARKER_RE = re.compile(r"^\s*\d+\s*[.)]\s*")
LEADING_COMPONENT_DOT_RE = re.compile(r"^\s*\.(?=[A-Za-z_])")
WHITESPACE_RE = re.compile(r"\s+")
PROTECTED_TOKENS = [
    "__PROTECTED_ALPHA__",
    "__PROTECTED_BRAVO__",
    "__PROTECTED_CHARLIE__",
    "__PROTECTED_DELTA__",
    "__PROTECTED_ECHO__",
    "__PROTECTED_FOXTROT__",
    "__PROTECTED_GOLF__",
    "__PROTECTED_HOTEL__",
    "__PROTECTED_INDIA__",
    "__PROTECTED_JULIET__",
]

SERVICE_CRITICALITY = {
    "login-service": "HIGH",
    "board-service": "MEDIUM",
    "batch-service": "LOW",
}
CRITICALITY_SCORE = {"HIGH": 30, "MEDIUM": 15, "LOW": 5}
LEVEL_SCORE = {"ERROR": 50, "WARN": 20, "INFO": 5}
_PIPELINE_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
KNOWN_SIMILARITY_THRESHOLD = 0.88
DUPLICATE_SIMILARITY_THRESHOLD = 0.93
DUPLICATE_MIN_TOTAL_OCCURRENCE = 2
DUPLICATE_MIN_STRUCTURE_SIMILARITY = 0.74
DUPLICATE_MAX_VARIABLE_TOKEN_RATIO = 0.35


@lru_cache(maxsize=1)
def _normalization_rules() -> tuple[tuple[str, str], ...]:
    db_path = _resolve_db_path()
    if not Path(db_path).exists():
        return ()
    try:
        with sqlite3.connect(db_path) as conn:
            approved_rows = conn.execute(
                """
                SELECT suggested_regex, suggested_template
                FROM pattern_duplicate_candidates
                WHERE status='approved'
                ORDER BY datetime(updated_at) DESC, candidate_key DESC
                """
            ).fetchall()
            rule_rows = conn.execute(
                """
                SELECT match_regex, template
                FROM pattern_normalization_rules
                WHERE enabled=1
                ORDER BY
                    CASE WHEN name LIKE 'duplicate:%' THEN 1 ELSE 0 END DESC,
                    priority DESC,
                    id DESC
                """
            ).fetchall()
    except sqlite3.Error:
        return ()
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    for row in [*approved_rows, *rule_rows]:
        for match_regex in _duplicate_regex_variants(str(row[0])):
            rule = (match_regex, str(row[1]))
            if rule in seen:
                continue
            seen.add(rule)
            ordered.append(rule)
    return tuple(ordered)


def _duplicate_regex_variants(match_regex: str) -> tuple[str, ...]:
    relaxed = _allow_trailing_key_values(match_regex)
    if relaxed == match_regex:
        return (match_regex,)
    return (relaxed, match_regex)


def _allow_trailing_key_values(match_regex: str) -> str:
    suffix = r"(?:\s+[A-Za-z_][\w.-]*=\S+)*\s*$"
    for ending in (r"\s+$", r"\s*$", "$"):
        if match_regex.endswith(ending):
            return match_regex[: -len(ending)] + suffix
    return match_regex


def clear_normalization_rule_cache() -> None:
    """Clear cached pattern normalization rules after rule changes."""

    _normalization_rules.cache_clear()


def _apply_normalization_rules(text: str) -> str:
    for match_regex, template in _normalization_rules():
        try:
            if re.search(match_regex, text, flags=re.IGNORECASE):
                return re.sub(match_regex, template, text, count=1, flags=re.IGNORECASE)
        except re.error:
            continue
    return text


def _protect_semantic_values(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        if len(protected) >= len(PROTECTED_TOKENS):
            return match.group(0)
        token = PROTECTED_TOKENS[len(protected)]
        protected[token] = f"{match.group(1)}: {match.group(2).strip()}"
        return token

    return SEMANTIC_VALUE_RE.sub(replace, text), protected


def _protect_url_fields(text: str, protected: dict[str, str]) -> str:
    def replace(match: re.Match[str]) -> str:
        if len(protected) >= len(PROTECTED_TOKENS):
            return match.group(0)
        token = PROTECTED_TOKENS[len(protected)]
        protected[token] = f"{match.group(1)}: {match.group(2).strip()}"
        return token

    return URL_FIELD_RE.sub(replace, text)


def _restore_semantic_values(text: str, protected: dict[str, str]) -> str:
    for token, value in protected.items():
        text = text.replace(token, value)
    return text


def _json_list(value: list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_dict(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_json_list(value: str) -> list[Any]:
    try:
        loaded = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return loaded if isinstance(loaded, list) else []


def _load_json_dict(value: str) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _normalize_url(match: re.Match[str]) -> str:
    raw = match.group(0).rstrip(".,)")
    suffix = match.group(0)[len(raw) :]
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return "URL" + suffix
    path_parts = [
        (
            "*"
            if UUID_RE.fullmatch(part) or part.isdigit() or HASH_LIKE_RE.fullmatch(part)
            else part
        )
        for part in parsed.path.split("/")
    ]
    query = "&".join(
        f"{key}=*" for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    )
    normalized = urlunsplit(("URL", parsed.netloc, "/".join(path_parts), query, ""))
    return normalized + suffix


def _normalize_windows_path(match: re.Match[str]) -> str:
    path = match.group(0)
    filename = path.rsplit("\\", 1)[-1]
    return f"PATH\\{filename}"


def normalize_log_text(value: str) -> str:
    """Replace volatile values so equal log templates share one fingerprint."""
    text = value or ""
    text = _apply_normalization_rules(text)
    text = EXCEL_NEWLINE_RE.sub(" ", text)
    text, protected = _protect_semantic_values(text)
    text = URL_RE.sub(_normalize_url, text)
    text = _protect_url_fields(text, protected)
    text = WINDOWS_PATH_RE.sub(_normalize_windows_path, text)
    text = DATE_TIME_RE.sub("*", text)
    text = KOREAN_TIME_RE.sub("*", text)
    text = EMAIL_RE.sub("*", text)
    text = HEX_ERROR_RE.sub("*", text)
    text = HASH_LIKE_RE.sub("*", text)
    text = COMPILER_GENERATED_MEMBER_RE.sub(r"\1__*", text)
    text = CS_LINE_RE.sub(r"\1*", text)
    text = ANONYMOUS_LINE_RE.sub(r"\1*:*", text)
    text = LEADING_LIST_MARKER_RE.sub("", text)
    text = LEADING_COMPONENT_DOT_RE.sub("", text)
    text = UUID_RE.sub("*", text)
    text = JSON_STRING_VALUE_RE.sub(r'\1"*"', text)
    text = JSON_LITERAL_VALUE_RE.sub(r"\1*", text)
    text = QUOTED_VOLATILE_RE.sub('"*"', text)
    text = ASSIGNED_VALUE_RE.sub(r"\1*", text)
    text = re.sub(
        r"(\b[A-Za-z_][\w.-]*(?:ID|Id|Status|Code|No|Number|Seq|Date|Time|Token|Key|"
        r"GUID|UUID)\b)\s*[:=]\s*\*",
        r"\1 *",
        text,
    )
    text = IDENTIFIER_KEY_VALUE_RE.sub(r"\1*", text)
    text = KOREAN_HONORIFIC_NUMBER_RE.sub("*", text)
    text = NUMERIC_RE.sub("*", text)
    text = re.sub(r"\*\s*,\s*", "* ", text)
    text = re.sub(r"\s*:\s*", ": ", text)
    text = re.sub(r"\s*=\s*", " = ", text)
    text = _restore_semantic_values(text, protected)
    return WHITESPACE_RE.sub(" ", text).strip()


def normalize_stacktrace(value: str) -> str:
    """Normalize stack traces with the same volatile-token rules used for messages."""
    if str(value).strip().lower() == "nan":
        return ""
    return normalize_log_text(value)


def fingerprint_id(service_name: str, level: str, message: str, stacktrace: str) -> str:
    """Create a stable short fingerprint identifier from normalized error content."""
    raw = (
        f"{service_name}|{level}|"
        f"{normalize_log_text(message)}|{normalize_stacktrace(stacktrace)}"
    )
    return "FP-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:6].upper()


def ensure_schema(conn: sqlite3.Connection) -> None:
    """Create all scenario tables required by SC-001 through SC-007."""
    cur = conn.cursor()
    # Migrate older demo tables that used a service-level impact schema.
    existing_columns = [
        row[1]
        for row in cur.execute("PRAGMA table_info(impact_evaluations)").fetchall()
    ]
    if existing_columns and "fingerprint" not in existing_columns:
        cur.execute("DROP TABLE impact_evaluations")
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS service_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            service_name TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            stack_trace TEXT DEFAULT '',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS fingerprints (
            fingerprint TEXT PRIMARY KEY,
            occurrence_count INTEGER NOT NULL,
            log_level TEXT NOT NULL,
            message TEXT NOT NULL,
            stacktrace TEXT NOT NULL,
            service_name TEXT NOT NULL,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS known_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fingerprint TEXT,
            category TEXT NOT NULL,
            sub_category TEXT NOT NULL,
            cause TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            confidence TEXT NOT NULL DEFAULT 'HIGH'
        );
        CREATE TABLE IF NOT EXISTS log_analysis_results (
            fingerprint TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            sub_category TEXT NOT NULL,
            is_known_pattern INTEGER NOT NULL,
            is_new_pattern INTEGER NOT NULL,
            pattern_status TEXT NOT NULL DEFAULT 'new_pattern',
            match_source TEXT DEFAULT '',
            similar_fingerprint TEXT DEFAULT '',
            similarity_score REAL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS anomaly_results (
            fingerprint TEXT PRIMARY KEY,
            anomaly_detected INTEGER NOT NULL,
            spike_ratio REAL NOT NULL,
            severity TEXT NOT NULL,
            anomaly_type TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS anomaly_daily_counts (
            service_name TEXT NOT NULL,
            analysis_date TEXT NOT NULL,
            anomaly_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(service_name, analysis_date)
        );
        CREATE TABLE IF NOT EXISTS impact_evaluations (
            fingerprint TEXT PRIMARY KEY,
            risk_score INTEGER NOT NULL,
            risk_level TEXT NOT NULL,
            detected INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS exception_registry (
            fingerprint TEXT PRIMARY KEY,
            reason TEXT NOT NULL,
            message TEXT DEFAULT '',
            log_level TEXT DEFAULT '',
            service_name TEXT DEFAULT '',
            normalized_message TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS knowledge_cards (
            card_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            cause TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence TEXT NOT NULL,
            resolution_method TEXT DEFAULT '',
            title TEXT DEFAULT '',
            summary TEXT DEFAULT '',
            symptoms TEXT DEFAULT '[]',
            evidence_text TEXT DEFAULT '',
            root_cause TEXT DEFAULT '',
            remediation_steps TEXT DEFAULT '[]',
            verification_steps TEXT DEFAULT '[]',
            prevention_steps TEXT DEFAULT '[]',
            metadata_json TEXT DEFAULT '{}',
            rag_document TEXT DEFAULT '',
            embedding_status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS log_processing_state (
            service_name TEXT PRIMARY KEY,
            last_rowid INTEGER NOT NULL DEFAULT 0,
            last_processed_at TEXT DEFAULT '',
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS processed_log_offsets (
            service_name TEXT NOT NULL,
            log_rowid INTEGER NOT NULL,
            fingerprint TEXT NOT NULL,
            processed_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(service_name, log_rowid)
        );
        CREATE TABLE IF NOT EXISTS pattern_time_series_metrics (
            service_name TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            bucket_start TEXT NOT NULL,
            bucket_size TEXT NOT NULL,
            total_count INTEGER NOT NULL DEFAULT 0,
            error_count INTEGER NOT NULL DEFAULT 0,
            warn_count INTEGER NOT NULL DEFAULT 0,
            info_count INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            PRIMARY KEY(service_name, fingerprint, bucket_start, bucket_size)
        );
        CREATE TABLE IF NOT EXISTS pattern_normalization_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            match_regex TEXT NOT NULL,
            template TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            priority INTEGER NOT NULL DEFAULT 100,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pattern_duplicate_candidates (
            candidate_key TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            log_level TEXT NOT NULL,
            signature TEXT NOT NULL,
            fingerprints_json TEXT NOT NULL,
            suggested_regex TEXT NOT NULL,
            suggested_template TEXT NOT NULL,
            confidence REAL NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS fingerprint_aliases (
            old_fingerprint TEXT PRIMARY KEY,
            canonical_fingerprint TEXT NOT NULL,
            reason TEXT DEFAULT '',
            rule_id INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS fingerprint_merge_groups (
            group_id TEXT PRIMARY KEY,
            candidate_key TEXT NOT NULL,
            canonical_fingerprint TEXT NOT NULL,
            service_name TEXT NOT NULL,
            log_level TEXT NOT NULL,
            representative_template TEXT NOT NULL,
            member_fingerprints_json TEXT NOT NULL,
            avg_similarity REAL NOT NULL DEFAULT 0,
            min_similarity REAL NOT NULL DEFAULT 0,
            total_occurrence_count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS event_time_windows (
            window_id TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            bucket_start TEXT NOT NULL,
            bucket_size TEXT NOT NULL,
            total_events INTEGER NOT NULL DEFAULT 0,
            error_events INTEGER NOT NULL DEFAULT 0,
            warn_events INTEGER NOT NULL DEFAULT 0,
            info_events INTEGER NOT NULL DEFAULT 0,
            unique_fingerprints INTEGER NOT NULL DEFAULT 0,
            known_fingerprint_count INTEGER NOT NULL DEFAULT 0,
            new_fingerprint_count INTEGER NOT NULL DEFAULT 0,
            anomaly_count INTEGER NOT NULL DEFAULT 0,
            max_risk_score INTEGER NOT NULL DEFAULT 0,
            top_fingerprints_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(service_name, bucket_start, bucket_size)
        );
        CREATE TABLE IF NOT EXISTS system_state_vectors (
            vector_id TEXT PRIMARY KEY,
            scope_key TEXT NOT NULL,
            service_name TEXT NOT NULL,
            bucket_start TEXT NOT NULL,
            bucket_size TEXT NOT NULL,
            feature_schema_version TEXT NOT NULL,
            features_json TEXT NOT NULL,
            vector_json TEXT NOT NULL,
            label TEXT NOT NULL DEFAULT 'normal',
            incident_id TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(scope_key, bucket_start, bucket_size, feature_schema_version)
        );
        """)

    for column, definition in {
        "pattern_status": "TEXT NOT NULL DEFAULT 'new_pattern'",
        "match_source": "TEXT DEFAULT ''",
        "similar_fingerprint": "TEXT DEFAULT ''",
        "similarity_score": "REAL",
    }.items():
        analysis_columns = [
            row[1]
            for row in cur.execute("PRAGMA table_info(log_analysis_results)").fetchall()
        ]
        if column not in analysis_columns:
            cur.execute(
                f"ALTER TABLE log_analysis_results ADD COLUMN {column} {definition}"
            )
    for column, definition in {
        "resolution_method": "TEXT DEFAULT ''",
        "title": "TEXT DEFAULT ''",
        "summary": "TEXT DEFAULT ''",
        "symptoms": "TEXT DEFAULT '[]'",
        "evidence_text": "TEXT DEFAULT ''",
        "root_cause": "TEXT DEFAULT ''",
        "remediation_steps": "TEXT DEFAULT '[]'",
        "verification_steps": "TEXT DEFAULT '[]'",
        "prevention_steps": "TEXT DEFAULT '[]'",
        "metadata_json": "TEXT DEFAULT '{}'",
        "rag_document": "TEXT DEFAULT ''",
        "embedding_status": "TEXT DEFAULT 'pending'",
    }.items():
        knowledge_columns = [
            row[1]
            for row in cur.execute("PRAGMA table_info(knowledge_cards)").fetchall()
        ]
        if column not in knowledge_columns:
            cur.execute(f"ALTER TABLE knowledge_cards ADD COLUMN {column} {definition}")
    for column, definition in {
        "message": "TEXT DEFAULT ''",
        "log_level": "TEXT DEFAULT ''",
        "service_name": "TEXT DEFAULT ''",
        "normalized_message": "TEXT DEFAULT ''",
    }.items():
        exception_columns = [
            row[1]
            for row in cur.execute("PRAGMA table_info(exception_registry)").fetchall()
        ]
        if column not in exception_columns:
            cur.execute(
                f"ALTER TABLE exception_registry ADD COLUMN {column} {definition}"
            )
    conn.commit()
    from app.patternops.registry import ensure_patternops_schema

    ensure_patternops_schema(conn)


def classify(message: str, stacktrace: str) -> tuple[str, str]:
    """Classify a fingerprint with deterministic rules that work without an LLM."""
    text = f"{message} {stacktrace}".lower()
    if "nullreference" in text or "개체 참조" in text:
        return "Exception", "NullReference"
    if "indexoutofrange" in text:
        return "Exception", "IndexOutOfRange"
    if "sqlexception" in text:
        return "Exception", "SqlException"
    if "ioexception" in text:
        return "Exception", "IOException"
    if "db timeout" in text or ("timeout" in text and "sql" in text):
        return "Timeout", "DB Timeout"
    if "http timeout" in text or "timeoutexception" in text:
        return "Timeout", "HTTP Timeout"
    if "memory" in text:
        return "Resource", "Memory"
    if "cpu" in text:
        return "Resource", "CPU"
    return "Unknown", "Unknown"


def risk_level(score: int) -> str:
    """Map a numeric risk score to the required severity band."""
    if score >= 90:
        return "Critical"
    if score >= 70:
        return "High"
    if score >= 40:
        return "Medium"
    return "Low"


def _pattern_cluster_context(item: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"service={item.get('service_name', '')}",
            f"fingerprint={item.get('fingerprint', '')}",
            f"log_level={item.get('log_level', '')}",
            f"normalized_message={item.get('normalized_message', '')}",
            f"context={item.get('stacktrace') or item.get('message') or ''}",
        ]
    )


def duplicate_candidate_signature(message: str) -> str:
    """Build an aggressive signature used only to suggest duplicate FP groups."""

    text = normalize_log_text(message)
    text = CANDIDATE_KEY_VALUE_RE.sub(r"\1*", text)
    text = re.sub(r"(\b[A-Za-z_][\w.]*)\s*:\s*(?=,|$)", r"\1:*", text)
    text = re.sub(r"(\b[A-Za-z_][\w.]*)(?:\s*:\s*)?\s+\*", r"\1:*", text)
    text = _generalize_candidate_paths(text)
    text = re.sub(r"(?:\s+[A-Za-z_][\w.-]*\s*=\s*\*)+$", "", text)
    text = re.sub(r"\s*,\s*", " ", text)
    text = re.sub(r"\s*:\s*", ":", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def _generalize_candidate_paths(text: str) -> str:
    text = re.sub(r"(/TEST_/erp_user/EA/NEW)/[^\s/]+/[^\s]+", r"\1/*/*", text)
    text = re.sub(
        r"(/\S+(?:/\S+){2,})/[^/\s]*\d[^/\s]*(\.[A-Za-z0-9]+)?",
        r"\1/*",
        text,
    )
    text = re.sub(r"PATH\\[^\s\\]*\.([A-Za-z0-9]+)", r"PATH\\*.\1", text)
    return text


def _duplicate_candidate_key(service_name: str, log_level: str, signature: str) -> str:
    raw = f"{service_name}|{log_level}|{signature}"
    return "DUP-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def _suggest_regex_from_duplicate_signature(signature: str) -> str:
    escaped = re.escape(signature)
    escaped = escaped.replace(r":\*", r":\s*[^,\s=>]*")
    escaped = escaped.replace(r"=\ \*", r"=>?\s*[^,\s=>]*")
    escaped = escaped.replace(r"\(\*\)", r"\(\d+\)")
    escaped = escaped.replace(r"/\*/\*", r"/[^/\s]+/[^/\s]+")
    escaped = escaped.replace(r"/\*", r"/[^/\s]+")
    escaped = re.sub(r"PATH\\\\[^,\s]+", r".+", escaped)
    escaped = escaped.replace(r"\*", r"[^,\s=>]*")
    escaped = escaped.replace(r"\ =\ ", r"\s+=\>?\s+")
    escaped = escaped.replace(r"\ ", r"[\s,]+")
    return f"^{escaped}$"


def _suggest_regex_from_duplicate_items(
    signature: str, items: list[dict[str, Any]]
) -> str:
    messages = [str(item.get("message") or "") for item in items if item.get("message")]
    if not messages:
        return _suggest_regex_from_duplicate_signature(signature)
    raw_regex = _wildcard_raw_duplicate_message(messages[0])
    try:
        if all(re.search(raw_regex, message, flags=re.IGNORECASE) for message in messages):
            return raw_regex
    except re.error:
        pass
    return _suggest_regex_from_duplicate_signature(signature)


def _wildcard_raw_duplicate_message(message: str) -> str:
    message = re.sub(r"(?:\s+[A-Za-z_][\w.-]*=\S+)+\s*$", "", message).rstrip()
    placeholders: list[tuple[str, str]] = [
        (r"/TEST_/erp_user/EA/NEW/[^\s/]+/[^\s]+", r"/TEST_/erp_user/EA/NEW/[^/\s]+/[^\s]+"),
        (r"[A-Za-z]:\\[^\s]+", r"[A-Za-z]:\\[^\s]+"),
        (r"\b[0-9a-f]{8,}\b", r"[0-9A-Fa-f]+"),
        (r"\b\d+\b", r"\d+"),
    ]
    tokenized = message
    replacements: dict[str, str] = {}

    def replace_key_value(match: re.Match[str]) -> str:
        token = f"__DUP_KV_TOKEN_{len(replacements)}__"
        prefix = re.escape(match.group(1)).replace(r"\ ", r"\s*")
        replacements[token] = prefix + r"[^,\s;}\]]+"
        return token

    tokenized = CANDIDATE_KEY_VALUE_RE.sub(replace_key_value, tokenized)
    for index, (pattern, replacement) in enumerate(placeholders):
        token = f"__DUP_TOKEN_{index}__"

        def replace(match: re.Match[str], *, token: str = token) -> str:
            return token

        tokenized = re.sub(pattern, replace, tokenized)
        replacements[token] = replacement

    escaped = re.escape(tokenized)
    for token, replacement in replacements.items():
        escaped = escaped.replace(re.escape(token), replacement)
    escaped = escaped.replace(r"\ ", r"\s+")
    return _allow_trailing_key_values(f"^{escaped}$")


def _suggest_template_from_duplicate_signature(signature: str) -> str:
    return signature.replace(":*", ":*")


def _message_tokens(message: str) -> list[str]:
    return [
        token
        for token in re.split(r"\s+", duplicate_candidate_signature(message))
        if token and token != "*"
    ]


def _structure_similarity(items: list[dict[str, Any]]) -> tuple[float, float]:
    token_lists = [_message_tokens(str(item.get("message") or "")) for item in items]
    token_lists = [tokens for tokens in token_lists if tokens]
    if len(token_lists) < 2:
        return 1.0, 0.0
    pair_scores: list[float] = []
    variable_ratios: list[float] = []
    for index, left in enumerate(token_lists):
        for right in token_lists[index + 1 :]:
            max_len = max(len(left), len(right), 1)
            common = len(set(left) & set(right))
            pair_scores.append(common / max_len)
            mismatch = sum(
                1
                for left_token, right_token in zip(left, right, strict=False)
                if left_token != right_token
            ) + abs(len(left) - len(right))
            variable_ratios.append(mismatch / max_len)
    return min(pair_scores or [1.0]), max(variable_ratios or [0.0])


def _candidate_regex_matches_all(regex: str, items: list[dict[str, Any]]) -> bool:
    try:
        return all(
            re.search(regex, str(item.get("message") or ""), flags=re.IGNORECASE)
            for item in items
        )
    except re.error:
        return False


def _candidate_items_allowed(items: list[dict[str, Any]]) -> bool:
    statuses = {str(item.get("pattern_status") or "") for item in items}
    if statuses and statuses <= {"known_exact"}:
        return False
    total_count = sum(int(item.get("occurrence_count") or 0) for item in items)
    if total_count < DUPLICATE_MIN_TOTAL_OCCURRENCE:
        return False
    structure_score, variable_ratio = _structure_similarity(items)
    return (
        structure_score >= DUPLICATE_MIN_STRUCTURE_SIMILARITY
        and variable_ratio <= DUPLICATE_MAX_VARIABLE_TOKEN_RATIO
    )


def _regex_matches_all_messages(regex: str, messages: list[str]) -> bool:
    try:
        return all(re.search(regex, message, flags=re.IGNORECASE) for message in messages)
    except re.error:
        return False


def _relax_regex_trailing_context(regex: str) -> str:
    if regex.endswith("$"):
        return f"{regex[:-1]}[\\s\\S]*$"
    return f"{regex}[\\s\\S]*$"


def _rescue_regex_from_raw_rows(
    signature: str, rows: list[sqlite3.Row | tuple[Any, ...]]
) -> str:
    items = [
        {
            "message": str(row[3] or ""),
            "fingerprint": "",
            "service_name": str(row[1] or ""),
            "log_level": str(row[2] or "").upper(),
            "occurrence_count": 1,
        }
        for row in rows
    ]
    messages = [str(item["message"]) for item in items]
    candidates = [
        _suggest_regex_from_duplicate_items(signature, items),
        _suggest_regex_from_duplicate_signature(signature),
    ]
    for regex in candidates:
        if _regex_matches_all_messages(regex, messages):
            return regex
        relaxed = _relax_regex_trailing_context(regex)
        if _regex_matches_all_messages(relaxed, messages):
            return relaxed
    unique_messages = list(dict.fromkeys(messages))
    if unique_messages:
        escaped_messages = [
            re.escape(message).replace(r"\ ", r"\s+") for message in unique_messages
        ]
        return f"^(?:{'|'.join(escaped_messages)})[\\s\\S]*$"
    return ""


def _raw_log_rows_for_fingerprints(
    conn: sqlite3.Connection,
    *,
    fingerprints: list[str],
    service_name: str,
    log_level: str,
) -> list[sqlite3.Row | tuple[Any, ...]]:
    if not fingerprints or not service_name or not log_level:
        return []
    placeholders = ",".join("?" for _ in fingerprints)
    rows = conn.execute(
        f"""
        SELECT sl.rowid, sl.service_name, sl.level, sl.message,
               COALESCE(sl.stack_trace, ''), sl.created_at
        FROM processed_log_offsets po
        JOIN service_logs sl
          ON sl.service_name=po.service_name AND sl.rowid=po.log_rowid
        WHERE po.fingerprint IN ({placeholders})
          AND sl.service_name=?
          AND upper(sl.level)=?
        ORDER BY sl.rowid ASC
        """,
        [*fingerprints, service_name, log_level],
    ).fetchall()
    deduped: dict[int, sqlite3.Row | tuple[Any, ...]] = {
        int(row[0]): row for row in rows
    }
    service_rows = conn.execute(
        """
        SELECT rowid, service_name, level, message, COALESCE(stack_trace, ''), created_at
        FROM service_logs
        WHERE service_name=? AND upper(level)=?
        ORDER BY rowid ASC
        """,
        (service_name, log_level),
    ).fetchall()
    fingerprint_set = set(fingerprints)
    for row in service_rows:
        fp = fingerprint_id(
            str(row[1]),
            str(row[2]).upper(),
            str(row[3] or ""),
            str(row[4] or ""),
        )
        if fp in fingerprint_set:
            deduped[int(row[0])] = row
    return list(deduped.values())


def detect_duplicate_pattern_candidates(
    groups: list[dict[str, Any]], *, min_group_size: int = 2
) -> list[dict[str, Any]]:
    """Persist and return duplicate pattern candidates for human review."""

    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    candidates_by_key: dict[str, dict[str, Any]] = {}
    for group in groups:
        fingerprint = str(group.get("fingerprint") or "")
        message = str(group.get("message") or "")
        service_name = str(group.get("service_name") or "")
        log_level = str(group.get("log_level") or "").upper()
        if not fingerprint or not message or not service_name or not log_level:
            continue
        signature = duplicate_candidate_signature(message)
        if not signature or signature == normalize_log_text(message):
            continue
        buckets.setdefault((service_name, log_level, signature), []).append(group)

    for semantic_group in _semantic_duplicate_groups(groups):
        if len(semantic_group) < min_group_size:
            continue
        representative = semantic_group[0]
        service_name = str(representative.get("service_name") or "")
        log_level = str(representative.get("log_level") or "").upper()
        signature = _common_duplicate_signature(semantic_group)
        if service_name and log_level and signature:
            buckets.setdefault((service_name, log_level, signature), []).extend(
                semantic_group
            )

    candidates: list[dict[str, Any]] = []
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        for (service_name, log_level, signature), items in buckets.items():
            deduped_items = {
                str(item.get("fingerprint") or ""): item
                for item in items
                if item.get("fingerprint")
            }
            items = list(deduped_items.values())
            if not _candidate_items_allowed(items):
                continue
            fingerprints = sorted(
                {
                    str(item.get("fingerprint") or "")
                    for item in items
                    if item.get("fingerprint")
                }
            )
            if len(fingerprints) < min_group_size:
                continue
            candidate_key = _duplicate_candidate_key(
                service_name, log_level, signature
            )
            existing = conn.execute(
                """
                SELECT status
                FROM pattern_duplicate_candidates
                WHERE candidate_key=?
                """,
                (candidate_key,),
            ).fetchone()
            if existing and str(existing[0]) in {"approved", "rejected"}:
                continue
            confidence = min(0.99, 0.82 + (0.03 * min(len(fingerprints), 5)))
            reason = (
                "Fingerprints share the same aggressive normalization signature; "
                "differences are limited to volatile fields and passed structure checks."
            )
            suggested_regex = _suggest_regex_from_duplicate_items(signature, items)
            if not _candidate_regex_matches_all(suggested_regex, items):
                continue
            suggested_template = _suggest_template_from_duplicate_signature(signature)
            conn.execute(
                """
                INSERT INTO pattern_duplicate_candidates(
                    candidate_key, service_name, log_level, signature,
                    fingerprints_json, suggested_regex, suggested_template,
                    confidence, reason, status, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)
                ON CONFLICT(candidate_key) DO UPDATE SET
                    fingerprints_json=excluded.fingerprints_json,
                    suggested_regex=excluded.suggested_regex,
                    suggested_template=excluded.suggested_template,
                    confidence=excluded.confidence,
                    reason=excluded.reason,
                    status='pending',
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    candidate_key,
                    service_name,
                    log_level,
                    signature,
                    _json_list(fingerprints),
                    suggested_regex,
                    suggested_template,
                    confidence,
                    reason,
                ),
            )
            candidates.append(
                {
                    "candidate_key": candidate_key,
                    "service_name": service_name,
                    "log_level": log_level,
                    "signature": signature,
                    "fingerprints": fingerprints,
                    "suggested_regex": suggested_regex,
                    "suggested_template": suggested_template,
                    "confidence": confidence,
                    "reason": reason,
                    "status": "pending",
                }
            )
            candidates_by_key[candidate_key] = candidates[-1]
        conn.commit()
    return list(candidates_by_key.values())


def _common_duplicate_signature(items: list[dict[str, Any]]) -> str:
    signatures = [
        duplicate_candidate_signature(str(item.get("message") or ""))
        for item in items
        if item.get("message")
    ]
    if not signatures:
        return ""
    common = signatures[0]
    for signature in signatures[1:]:
        common = _merge_signature_pair(common, signature)
    return common


def _merge_signature_pair(left: str, right: str) -> str:
    left_parts = left.split()
    right_parts = right.split()
    if len(left_parts) != len(right_parts):
        return left if len(left) <= len(right) else right
    merged = [
        left_part if left_part == right_part else _merge_signature_token(left_part, right_part)
        for left_part, right_part in zip(left_parts, right_parts, strict=False)
    ]
    return " ".join(merged)


def _merge_signature_token(left: str, right: str) -> str:
    if "/" in left and "/" in right:
        left_parts = left.split("/")
        right_parts = right.split("/")
        if len(left_parts) == len(right_parts):
            return "/".join(
                left_part if left_part == right_part else "*"
                for left_part, right_part in zip(left_parts, right_parts, strict=False)
            )
    if "." in left and "." in right:
        left_stem, _, left_suffix = left.rpartition(".")
        right_stem, _, right_suffix = right.rpartition(".")
        if left_suffix.lower() == right_suffix.lower() and left_stem != right_stem:
            return f"*.{left_suffix}"
    return "*"


def _semantic_duplicate_groups(groups: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    lookup = {str(group.get("fingerprint") or ""): group for group in groups}
    contexts = [_pattern_cluster_context(group) for group in groups]
    if not contexts:
        return []
    try:
        match_groups = find_similar_pattern_clusters_batch(queries=contexts)
    except Exception:  # noqa: BLE001
        return []

    edges: dict[str, set[str]] = {fingerprint: set() for fingerprint in lookup}
    for index, matches in enumerate(match_groups):
        if index >= len(groups):
            continue
        source = str(groups[index].get("fingerprint") or "")
        source_group = lookup.get(source)
        if not source or source_group is None:
            continue
        for match in matches:
            similarity = float(match.get("similarity") or 0)
            if similarity < DUPLICATE_SIMILARITY_THRESHOLD:
                continue
            metadata = match.get("metadata") or {}
            target = str(metadata.get("fingerprint") or match.get("id") or "")
            if ":" in target:
                target = target.rsplit(":", 1)[-1]
            target_group = lookup.get(target)
            if (
                not target_group
                or target == source
                or target_group.get("service_name") != source_group.get("service_name")
                or str(target_group.get("log_level") or "").upper()
                != str(source_group.get("log_level") or "").upper()
            ):
                continue
            edges[source].add(target)
            edges[target].add(source)

    seen: set[str] = set()
    components: list[list[dict[str, Any]]] = []
    for fingerprint in edges:
        if fingerprint in seen or not edges[fingerprint]:
            continue
        stack = [fingerprint]
        component: list[dict[str, Any]] = []
        seen.add(fingerprint)
        while stack:
            current = stack.pop()
            component.append(lookup[current])
            for next_fingerprint in edges[current]:
                if next_fingerprint not in seen:
                    seen.add(next_fingerprint)
                    stack.append(next_fingerprint)
        if len(component) >= 2:
            components.append(component)
    return components


def fetch_duplicate_pattern_candidates(
    *, status: str = "pending", limit: int = 50
) -> list[dict[str, Any]]:
    """Return duplicate pattern candidates for review."""

    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        params: list[Any] = []
        where_sql = ""
        if status:
            where_sql = "WHERE status=?"
            params.append(status)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT candidate_key, service_name, log_level, signature,
                   fingerprints_json, suggested_regex, suggested_template,
                   confidence, reason, status, created_at, updated_at
            FROM pattern_duplicate_candidates
            {where_sql}
            ORDER BY confidence DESC, datetime(updated_at) DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        candidates = []
        all_fingerprints: set[str] = set()
        for row in rows:
            fingerprints = [str(item) for item in _load_json_list(str(row[4]))]
            all_fingerprints.update(fingerprints)
            candidates.append(
                {
                    "candidate_key": str(row[0]),
                    "service_name": str(row[1]),
                    "log_level": str(row[2]),
                    "signature": str(row[3]),
                    "fingerprints": fingerprints,
                    "suggested_regex": str(row[5]),
                    "suggested_template": str(row[6]),
                    "confidence": float(row[7] or 0),
                    "reason": str(row[8]),
                    "status": str(row[9]),
                    "created_at": str(row[10]),
                    "updated_at": str(row[11]),
                }
            )
        details: dict[str, dict[str, Any]] = {}
        if all_fingerprints:
            placeholders = ",".join("?" for _ in all_fingerprints)
            detail_rows = conn.execute(
                f"""
                SELECT fingerprint, service_name, log_level, message, stacktrace,
                       occurrence_count, first_seen, last_seen
                FROM fingerprints
                WHERE fingerprint IN ({placeholders})
                """,
                sorted(all_fingerprints),
            ).fetchall()
            details = {
                str(row[0]): {
                    "fingerprint": str(row[0]),
                    "service_name": str(row[1] or ""),
                    "log_level": str(row[2] or ""),
                    "message": str(row[3] or ""),
                    "normalized_message": normalize_log_text(str(row[3] or "")),
                    "stacktrace": str(row[4] or ""),
                    "occurrence_count": int(row[5] or 0),
                    "first_seen": str(row[6] or ""),
                    "last_seen": str(row[7] or ""),
                }
                for row in detail_rows
            }
        for candidate in candidates:
            candidate["fingerprint_details"] = {
                fingerprint: details.get(fingerprint, {"fingerprint": fingerprint})
                for fingerprint in candidate["fingerprints"]
            }
    return candidates


def update_duplicate_pattern_candidate_status(
    candidate_key: str, status: str
) -> dict[str, Any] | None:
    """Mark a duplicate candidate as approved or rejected."""

    if status not in {"approved", "rejected", "pending"}:
        raise ValueError("status must be approved, rejected, or pending")
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        row = conn.execute(
            """
            SELECT candidate_key
            FROM pattern_duplicate_candidates
            WHERE candidate_key=?
            """,
            (candidate_key,),
        ).fetchone()
        if row is None:
            return None
        conn.execute(
            """
            UPDATE pattern_duplicate_candidates
            SET status=?, updated_at=CURRENT_TIMESTAMP
            WHERE candidate_key=?
            """,
            (status, candidate_key),
        )
        _sync_fingerprint_merge_group_status(conn)
        conn.commit()
    clear_normalization_rule_cache()
    _PIPELINE_CACHE.clear()
    candidates = fetch_duplicate_pattern_candidates(status="", limit=500)
    return next(
        (
            candidate
            for candidate in candidates
            if candidate["candidate_key"] == candidate_key
        ),
        None,
    )


def merge_duplicate_pattern_candidate(candidate_key: str, *, rule_id: int) -> dict[str, Any]:
    """Merge existing SQLite fingerprints covered by an approved duplicate rule."""

    candidates = fetch_duplicate_pattern_candidates(status="", limit=500)
    candidate = next(
        (item for item in candidates if item["candidate_key"] == candidate_key),
        None,
    )
    if candidate is None:
        return {"merged": False, "reason": "candidate_not_found"}
    fingerprints = [str(fp) for fp in candidate.get("fingerprints", []) if fp]
    if len(fingerprints) < 2:
        return {"merged": False, "reason": "not_enough_fingerprints"}

    placeholders = ",".join("?" for _ in fingerprints)
    canonical_item: dict[str, Any] | None = None
    old_doc_ids: list[str] = []
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        canonical_template = str(candidate.get("suggested_template") or "")
        suggested_regex = str(candidate.get("suggested_regex") or "")
        raw_rows: list[sqlite3.Row | tuple[Any, ...]] = []
        force_canonical_from_raw = False
        try:
            matcher = re.compile(suggested_regex, flags=re.IGNORECASE)
        except re.error:
            matcher = None
        candidate_service = str(candidate.get("service_name") or "")
        candidate_level = str(candidate.get("log_level") or "").upper()
        if matcher and candidate_service and candidate_level:
            service_rows = conn.execute(
                """
                SELECT rowid, service_name, level, message, COALESCE(stack_trace, ''), created_at
                FROM service_logs
                WHERE service_name=? AND upper(level)=?
                """,
                (candidate_service, candidate_level),
            ).fetchall()
            raw_rows = [
                row
                for row in service_rows
                if matcher.search(str(row[3] or ""))
            ]
        if not raw_rows and candidate_service and candidate_level:
            rescued_rows = _raw_log_rows_for_fingerprints(
                conn,
                fingerprints=fingerprints,
                service_name=candidate_service,
                log_level=candidate_level,
            )
            if len(rescued_rows) >= 2:
                raw_rows = rescued_rows
                force_canonical_from_raw = True
                raw_signature_items = [
                    {
                        "message": str(row[3] or ""),
                        "fingerprint": "",
                        "service_name": str(row[1] or ""),
                        "log_level": str(row[2] or "").upper(),
                        "occurrence_count": 1,
                    }
                    for row in raw_rows
                ]
                signature = _common_duplicate_signature(raw_signature_items) or str(
                    candidate.get("signature") or ""
                )
                rescued_regex = _rescue_regex_from_raw_rows(signature, raw_rows)
                if rescued_regex:
                    suggested_regex = rescued_regex
                    conn.execute(
                        """
                        UPDATE pattern_duplicate_candidates
                        SET suggested_regex=?, updated_at=CURRENT_TIMESTAMP
                        WHERE candidate_key=?
                        """,
                        (suggested_regex, candidate_key),
                    )
                    conn.execute(
                        """
                        UPDATE pattern_normalization_rules
                        SET match_regex=?
                        WHERE id=?
                        """,
                        (suggested_regex, rule_id),
                    )
        if raw_rows and force_canonical_from_raw:
            canonical_log_rows = raw_rows
            representative_log = canonical_log_rows[0]
            representative_service = str(representative_log[1] or "")
            representative_level = str(representative_log[2]).upper()
            representative_message = str(representative_log[3] or "")
            representative_stack = ""
            canonical_fingerprint = fingerprint_id(
                representative_service,
                representative_level,
                canonical_template or representative_message,
                "",
            )
            occurrence_count = len(canonical_log_rows)
            first_seen = min(str(row[5] or "") for row in canonical_log_rows)
            last_seen = max(str(row[5] or "") for row in canonical_log_rows)
            old_fingerprints = list(fingerprints)
            existing_canonical = conn.execute(
                """
                SELECT occurrence_count, first_seen, last_seen
                FROM fingerprints
                WHERE fingerprint=?
                """,
                (canonical_fingerprint,),
            ).fetchone()
            if existing_canonical and canonical_fingerprint not in old_fingerprints:
                occurrence_count = max(occurrence_count, int(existing_canonical[0] or 0))
                first_seen = min(first_seen, str(existing_canonical[1] or first_seen))
                last_seen = max(last_seen, str(existing_canonical[2] or last_seen))
        if raw_rows and not force_canonical_from_raw:
            recalculated_from_raw: dict[str, list[sqlite3.Row | tuple[Any, ...]]] = {}
            for row in raw_rows:
                new_fp = fingerprint_id(
                    str(row[1]),
                    str(row[2]).upper(),
                    str(row[3] or ""),
                    str(row[4] or ""),
                )
                recalculated_from_raw.setdefault(new_fp, []).append(row)
            canonical_fingerprint, canonical_log_rows = max(
                recalculated_from_raw.items(), key=lambda item: len(item[1])
            )
            if len(canonical_log_rows) < 2:
                return {"merged": False, "reason": "rule_did_not_converge"}
            occurrence_count = len(canonical_log_rows)
            first_seen = min(str(row[5] or "") for row in canonical_log_rows)
            last_seen = max(str(row[5] or "") for row in canonical_log_rows)
            representative_log = canonical_log_rows[0]
            representative_service = str(representative_log[1] or "")
            representative_level = str(representative_log[2] or "").upper()
            representative_message = str(representative_log[3] or "")
            representative_stack = str(representative_log[4] or "")
            old_fingerprints = list(fingerprints)
            existing_canonical = conn.execute(
                """
                SELECT occurrence_count, first_seen, last_seen
                FROM fingerprints
                WHERE fingerprint=?
                """,
                (canonical_fingerprint,),
            ).fetchone()
            if existing_canonical and canonical_fingerprint not in old_fingerprints:
                occurrence_count = max(occurrence_count, int(existing_canonical[0] or 0))
                first_seen = min(first_seen, str(existing_canonical[1] or first_seen))
                last_seen = max(last_seen, str(existing_canonical[2] or last_seen))
        elif not raw_rows:
            representative_service = ""
            representative_level = ""
            representative_message = ""
            representative_stack = ""
            canonical_log_rows = []
        rows = conn.execute(
            f"""
            SELECT fingerprint, occurrence_count, log_level, message, stacktrace,
                   service_name, first_seen, last_seen
            FROM fingerprints
            WHERE fingerprint IN ({placeholders})
            """,
            fingerprints,
        ).fetchall()
        if len(rows) < 2 and not raw_rows:
            return {"merged": False, "reason": "not_enough_existing_rows"}

        if not raw_rows:
            recalculated: dict[str, list[sqlite3.Row | tuple[Any, ...]]] = {}
            for row in rows:
                new_fp = fingerprint_id(
                    str(row[5]),
                    str(row[2]).upper(),
                    canonical_template or str(row[3] or ""),
                    str(row[4] or ""),
                )
                recalculated.setdefault(new_fp, []).append(row)
            canonical_fingerprint, canonical_rows = max(
                recalculated.items(), key=lambda item: len(item[1])
            )
            if len(canonical_rows) < 2:
                representative = rows[0]
                canonical_rows = rows
                canonical_fingerprint = fingerprint_id(
                    str(representative[5] or ""),
                    str(representative[2]).upper(),
                    canonical_template or str(representative[3] or ""),
                    "",
                )
            occurrence_count = sum(int(row[1] or 0) for row in canonical_rows)
            first_seen = min(str(row[6] or "") for row in canonical_rows)
            last_seen = max(str(row[7] or "") for row in canonical_rows)
            representative = canonical_rows[0]
            old_fingerprints = [str(row[0]) for row in canonical_rows]
            representative_service = str(representative[5] or "")
            representative_level = str(representative[2]).upper()
            representative_message = str(representative[3] or "")
            representative_stack = (
                "" if len(canonical_rows) == len(rows) else str(representative[4] or "")
            )
            existing_canonical = conn.execute(
                """
                SELECT occurrence_count, first_seen, last_seen
                FROM fingerprints
                WHERE fingerprint=?
                """,
                (canonical_fingerprint,),
            ).fetchone()
            if existing_canonical and canonical_fingerprint not in old_fingerprints:
                occurrence_count += int(existing_canonical[0] or 0)
                first_seen = min(first_seen, str(existing_canonical[1] or first_seen))
                last_seen = max(last_seen, str(existing_canonical[2] or last_seen))

        conn.execute(
            """
            REPLACE INTO fingerprints(
                fingerprint, occurrence_count, log_level, message, stacktrace,
                service_name, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_fingerprint,
                occurrence_count,
                representative_level,
                canonical_template or representative_message,
                normalize_stacktrace(representative_stack),
                representative_service,
                first_seen,
                last_seen,
            ),
        )
        canonical_item = {
            "fingerprint": canonical_fingerprint,
            "occurrence_count": occurrence_count,
            "log_level": representative_level,
            "message": canonical_template or representative_message,
            "normalized_message": normalize_log_text(
                canonical_template or representative_message
            ),
            "stacktrace": normalize_stacktrace(representative_stack),
            "service_name": representative_service,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "pattern_status": "known_exact",
            "match_source": "known_patterns",
            "similar_fingerprint": "",
            "similarity_score": None,
        }
        alias_fingerprints = set(old_fingerprints)
        for log_row in canonical_log_rows:
            row_service = str(log_row[1] or "")
            row_level = str(log_row[2]).upper()
            row_message = str(log_row[3] or "")
            row_stack = str(log_row[4] or "")
            alias_fingerprints.add(
                fingerprint_id(row_service, row_level, row_message, row_stack)
            )
            alias_fingerprints.add(
                fingerprint_id(
                    row_service,
                    row_level,
                    canonical_template or row_message,
                    row_stack,
                )
            )
        for old_fp in alias_fingerprints:
            if old_fp == canonical_fingerprint:
                continue
            old_doc_ids.append(f"{representative_service}:{old_fp}")
            conn.execute(
                """
                INSERT OR REPLACE INTO fingerprint_aliases(
                    old_fingerprint, canonical_fingerprint, reason, rule_id
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    old_fp,
                    canonical_fingerprint,
                    f"approved duplicate candidate {candidate_key}",
                    rule_id,
                ),
            )
            conn.execute(
                "UPDATE processed_log_offsets SET fingerprint=? WHERE fingerprint=?",
                (canonical_fingerprint, old_fp),
            )
            for metric in conn.execute(
                """
                SELECT service_name, bucket_start, bucket_size, total_count,
                       error_count, warn_count, info_count, first_seen, last_seen
                FROM pattern_time_series_metrics
                WHERE fingerprint=?
                """,
                (old_fp,),
            ).fetchall():
                conn.execute(
                    """
                    INSERT INTO pattern_time_series_metrics(
                        service_name, fingerprint, bucket_start, bucket_size,
                        total_count, error_count, warn_count, info_count,
                        first_seen, last_seen
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(service_name, fingerprint, bucket_start, bucket_size)
                    DO UPDATE SET
                        total_count=total_count + excluded.total_count,
                        error_count=error_count + excluded.error_count,
                        warn_count=warn_count + excluded.warn_count,
                        info_count=info_count + excluded.info_count,
                        first_seen=min(first_seen, excluded.first_seen),
                        last_seen=max(last_seen, excluded.last_seen)
                    """,
                    (
                        str(metric[0]),
                        canonical_fingerprint,
                        str(metric[1]),
                        str(metric[2]),
                        int(metric[3] or 0),
                        int(metric[4] or 0),
                        int(metric[5] or 0),
                        int(metric[6] or 0),
                        str(metric[7] or ""),
                        str(metric[8] or ""),
                    ),
                )
            conn.execute(
                "DELETE FROM pattern_time_series_metrics WHERE fingerprint=?",
                (old_fp,),
            )
            conn.execute("DELETE FROM fingerprints WHERE fingerprint=?", (old_fp,))
            conn.execute("DELETE FROM log_analysis_results WHERE fingerprint=?", (old_fp,))
            conn.execute("DELETE FROM anomaly_results WHERE fingerprint=?", (old_fp,))
            conn.execute("DELETE FROM impact_evaluations WHERE fingerprint=?", (old_fp,))
        for log_row in canonical_log_rows:
            conn.execute(
                """
                INSERT OR REPLACE INTO processed_log_offsets(
                    service_name, log_rowid, fingerprint
                ) VALUES (?, ?, ?)
                """,
                (str(log_row[1]), int(log_row[0]), canonical_fingerprint),
            )
        conn.execute(
            """
            INSERT INTO known_patterns(
                fingerprint, category, sub_category, cause, recommendation, confidence
            )
            SELECT ?, 'Manual', 'Merged Duplicate Pattern', ?, ?, 'HIGH'
            WHERE NOT EXISTS (
                SELECT 1 FROM known_patterns WHERE fingerprint=?
            )
            """,
            (
                canonical_fingerprint,
                f"Approved duplicate pattern candidate {candidate_key}",
                f"Pattern normalization rule #{rule_id} groups duplicate fingerprints.",
                canonical_fingerprint,
            ),
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO log_analysis_results(
                fingerprint, category, sub_category, is_known_pattern,
                is_new_pattern, pattern_status, match_source,
                similar_fingerprint, similarity_score
            ) VALUES (?, 'Manual', 'Merged Duplicate Pattern', 1, 0, 'known_exact',
                      'known_patterns', '', NULL)
            """,
            (canonical_fingerprint,),
        )
        _sync_fingerprint_merge_group_status(conn)
        conn.commit()

    _PIPELINE_CACHE.clear()
    chroma_result = delete_pattern_clusters(old_doc_ids)
    if canonical_item is not None:
        _upsert_pattern_clusters([canonical_item])
    return {
        "merged": True,
        "canonical_fingerprint": canonical_fingerprint,
        "merged_fingerprints": [
            fp for fp in old_fingerprints if fp != canonical_fingerprint
        ],
        "occurrence_count": occurrence_count,
        "chroma": chroma_result,
    }


def _top_similarity(matches: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = [m for m in matches if m.get("similarity") is not None]
    if not scored:
        return None
    return max(scored, key=lambda item: float(item.get("similarity") or 0))


def _exact_known_match(conn: sqlite3.Connection, fp: str) -> tuple[bool, str]:
    if conn.execute(
        "SELECT 1 FROM knowledge_cards WHERE fingerprint=? LIMIT 1", (fp,)
    ).fetchone():
        return True, "knowledge_cards"
    if conn.execute(
        "SELECT 1 FROM known_patterns WHERE fingerprint=? LIMIT 1", (fp,)
    ).fetchone():
        return True, "known_patterns"
    return False, ""


def _known_pattern_signature_map(
    conn: sqlite3.Connection,
) -> dict[tuple[str, str, str], str]:
    rows = conn.execute(
        """
        SELECT kp.fingerprint, fp.service_name, fp.log_level, fp.message
        FROM known_patterns kp
        JOIN fingerprints fp ON fp.fingerprint = kp.fingerprint
        WHERE kp.fingerprint IS NOT NULL AND kp.fingerprint <> ''
        """
    ).fetchall()
    signature_map: dict[tuple[str, str, str], str] = {}
    for fingerprint, service_name, log_level, message in rows:
        signature = duplicate_candidate_signature(str(message or ""))
        if not signature:
            continue
        key = (str(service_name or ""), str(log_level or "").upper(), signature)
        signature_map.setdefault(key, str(fingerprint or ""))
    return signature_map


def _canonical_fingerprint(
    conn: sqlite3.Connection,
    fp: str,
    *,
    service_name: str = "",
    log_level: str = "",
    message: str = "",
    known_signature_map: dict[tuple[str, str, str], str] | None = None,
) -> str:
    row = conn.execute(
        """
        SELECT canonical_fingerprint
        FROM fingerprint_aliases
        WHERE old_fingerprint=?
        LIMIT 1
        """,
        (fp,),
    ).fetchone()
    if row:
        return str(row[0] or fp)
    if known_signature_map is None or not service_name or not log_level or not message:
        return fp
    signature = duplicate_candidate_signature(message)
    return known_signature_map.get(
        (service_name, log_level.upper(), signature),
        fp,
    )


def _pattern_status(
    *,
    conn: sqlite3.Connection,
    item: dict[str, Any],
    existing_fingerprints: set[str],
) -> dict[str, Any]:
    context = _pattern_cluster_context(item)
    return _pattern_status_from_matches(
        conn=conn,
        item=item,
        existing_fingerprints=existing_fingerprints,
        approved_matches=find_similar_analysis_documents(query=context),
        observed_matches=find_similar_pattern_clusters(query=context),
    )


def _pattern_status_from_matches(
    *,
    conn: sqlite3.Connection,
    item: dict[str, Any],
    existing_fingerprints: set[str],
    approved_matches: list[dict[str, Any]],
    observed_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    fp = str(item["fingerprint"])
    known_exact, match_source = _exact_known_match(conn, fp)
    if known_exact:
        return {
            "pattern_status": "known_exact",
            "match_source": match_source,
            "similar_fingerprint": "",
            "similarity_score": None,
        }

    approved_match = _top_similarity(
        [
            match
            for match in approved_matches
            if (match.get("metadata") or {}).get("source")
            in {"approved_recommendation", "known_pattern"}
            or str(match.get("id") or "").startswith("knowledge-card:")
            or str(match.get("id") or "").startswith("known-pattern:")
        ]
    )
    observed_match = _top_similarity(
        [
            match
            for match in observed_matches
            if match.get("id") != f"{item.get('service_name')}:{fp}"
        ]
    )
    best_match = _top_similarity([m for m in [approved_match, observed_match] if m])
    if (
        best_match
        and float(best_match.get("similarity") or 0) >= KNOWN_SIMILARITY_THRESHOLD
    ):
        metadata = best_match.get("metadata") or {}
        similar_fp = str(metadata.get("fingerprint") or best_match.get("id") or "")
        source = (
            "incident_analyses" if best_match is approved_match else "pattern_clusters"
        )
        return {
            "pattern_status": "known_similar",
            "match_source": source,
            "similar_fingerprint": similar_fp,
            "similarity_score": float(best_match.get("similarity") or 0),
        }

    if fp in existing_fingerprints:
        metadata = best_match.get("metadata") if best_match else {}
        similar_fp = (
            str((metadata or {}).get("fingerprint") or best_match.get("id") or "")
            if best_match
            else ""
        )
        return {
            "pattern_status": "observed_existing",
            "match_source": "fingerprints",
            "similar_fingerprint": similar_fp,
            "similarity_score": (
                float(best_match.get("similarity") or 0) if best_match else 1.0
            ),
        }

    return {
        "pattern_status": "new_pattern",
        "match_source": "",
        "similar_fingerprint": "",
        "similarity_score": None,
    }


def _build_pattern_documents(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "doc_id": f"{item.get('service_name')}:{item.get('fingerprint')}",
            "text": _pattern_cluster_context(item),
            "metadata": {
                "service_name": str(item.get("service_name") or ""),
                "fingerprint": str(item.get("fingerprint") or ""),
                "log_level": str(item.get("log_level") or ""),
                "normalized_message": str(item.get("normalized_message") or ""),
                "occurrence_count": int(item.get("occurrence_count") or 0),
                "pattern_status": str(item.get("pattern_status") or ""),
            },
        }
        for item in items
    ]


def _upsert_pattern_cluster(item: dict[str, Any]) -> None:
    _upsert_pattern_clusters([item])


def _upsert_pattern_clusters(items: list[dict[str, Any]]) -> None:
    documents = _build_pattern_documents(items)
    if documents:
        save_pattern_clusters(documents)


def save_new_pattern_clusters(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    new_items = [
        item for item in items if str(item.get("pattern_status") or "") == "new_pattern"
    ]
    documents = _build_pattern_documents(new_items)
    if not documents:
        return None
    return save_pattern_clusters(documents)


def fetch_pattern_cluster(
    *, fingerprint: str, service_name: str | None = None
) -> dict[str, Any] | None:
    db_path = _resolve_db_path()
    if not Path(db_path).exists():
        return None
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        groups = _load_fingerprint_groups(conn, service_name)
    return groups.get(fingerprint)


def recommendation_for(
    conn: sqlite3.Connection, fp: str, sub_category: str
) -> dict[str, str]:
    """Return recommendation by Knowledge Card, Known Pattern, then rule fallback priority."""
    cur = conn.cursor()
    row = cur.execute(
        "SELECT cause, recommendation, confidence FROM knowledge_cards WHERE fingerprint=? ORDER BY created_at DESC LIMIT 1",
        (fp,),
    ).fetchone()
    if row:
        return {"cause": row[0], "recommendation": row[1], "confidence": row[2]}
    row = cur.execute(
        "SELECT cause, recommendation, confidence FROM known_patterns WHERE fingerprint=? OR sub_category=? ORDER BY fingerprint IS NULL ASC LIMIT 1",
        (fp, sub_category),
    ).fetchone()
    if row:
        return {"cause": row[0], "recommendation": row[1], "confidence": row[2]}
    rules = {
        "NullReference": ("Null 객체 참조", "Null Check 추가"),
        "IndexOutOfRange": ("컬렉션 범위 초과", "인덱스 경계 조건 검증 추가"),
        "SqlException": ("SQL 실행 오류", "쿼리와 DB 연결 상태를 점검"),
        "IOException": (
            "파일 또는 네트워크 I/O 오류",
            "경로 권한과 재시도 로직을 점검",
        ),
        "DB Timeout": ("DB 응답 지연", "슬로우 쿼리와 커넥션 풀을 점검"),
        "HTTP Timeout": (
            "외부 HTTP 응답 지연",
            "타임아웃/재시도/서킷브레이커 설정 점검",
        ),
    }
    cause, action = rules.get(
        sub_category, ("원인 미상", "로그와 최근 배포 변경사항을 추가 분석")
    )
    return {"cause": cause, "recommendation": action, "confidence": "MEDIUM"}


def _pipeline_signature(
    conn: sqlite3.Connection,
    service_name: str | None,
    cutoff: str | None,
    date_start: str | None = None,
    date_end: str | None = None,
) -> tuple[int, str]:
    where_parts = []
    params: list[Any] = []
    if service_name:
        where_parts.append("service_name=?")
        params.append(service_name)
    if cutoff:
        where_parts.append("created_at>=?")
        params.append(cutoff)
    if date_start:
        where_parts.append("substr(created_at, 1, 10)=?")
        params.append(date_start)
    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    row = conn.execute(
        f"SELECT COUNT(*), COALESCE(MAX(created_at), '') FROM service_logs {where_sql}",
        params,
    ).fetchone()
    return int(row[0] or 0), str(row[1] or "")


def _state_key(service_name: str | None) -> str:
    return service_name or "__all__"


def _last_processed_rowid(conn: sqlite3.Connection, service_name: str | None) -> int:
    row = conn.execute(
        "SELECT last_rowid FROM log_processing_state WHERE service_name=?",
        (_state_key(service_name),),
    ).fetchone()
    return int(row[0] or 0) if row else 0


def _save_processing_state(
    conn: sqlite3.Connection,
    service_name: str | None,
    last_rowid: int,
    last_created_at: str,
) -> None:
    conn.execute(
        """
        REPLACE INTO log_processing_state(service_name, last_rowid, last_processed_at, updated_at)
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (_state_key(service_name), last_rowid, last_created_at),
    )


def _bucket_start(value: str, bucket_size: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        parsed = datetime.utcnow()
    if bucket_size == "hour":
        return parsed.replace(minute=0, second=0, microsecond=0).isoformat(
            timespec="seconds"
        )
    return parsed.date().isoformat()


def _increment_pattern_metric(
    conn: sqlite3.Connection,
    *,
    service_name: str,
    fingerprint: str,
    level: str,
    created_at: str,
    bucket_size: str,
) -> None:
    bucket = _bucket_start(created_at, bucket_size)
    level_upper = level.upper()
    conn.execute(
        """
        INSERT INTO pattern_time_series_metrics(
            service_name, fingerprint, bucket_start, bucket_size,
            total_count, error_count, warn_count, info_count, first_seen, last_seen
        ) VALUES (?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
        ON CONFLICT(service_name, fingerprint, bucket_start, bucket_size)
        DO UPDATE SET
            total_count = total_count + 1,
            error_count = error_count + excluded.error_count,
            warn_count = warn_count + excluded.warn_count,
            info_count = info_count + excluded.info_count,
            first_seen = MIN(first_seen, excluded.first_seen),
            last_seen = MAX(last_seen, excluded.last_seen)
        """,
        (
            service_name,
            fingerprint,
            bucket,
            bucket_size,
            1 if level_upper == "ERROR" else 0,
            1 if level_upper in {"WARN", "WARNING"} else 0,
            1 if level_upper in {"INFO", "INFORMATION"} else 0,
            created_at,
            created_at,
        ),
    )


def _metric_baseline(
    conn: sqlite3.Connection, *, service_name: str, fingerprint: str
) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT bucket_start, total_count
        FROM pattern_time_series_metrics
        WHERE service_name=? AND fingerprint=? AND bucket_size='day'
        ORDER BY bucket_start DESC
        LIMIT 8
        """,
        (service_name, fingerprint),
    ).fetchall()
    if not rows:
        return {"latest_count": 0, "baseline_count": 0.0, "latest_bucket": ""}
    latest_count = int(rows[0][1] or 0)
    history = [int(row[1] or 0) for row in rows[1:]]
    baseline = round(sum(history) / len(history), 2) if history else 0.0
    return {
        "latest_bucket": str(rows[0][0]),
        "latest_count": latest_count,
        "baseline_count": baseline,
    }


def _merge_group_id(candidate_key: str) -> str:
    return "FMG-" + hashlib.sha1(candidate_key.encode("utf-8")).hexdigest()[:12].upper()


def _sync_fingerprint_merge_group_status(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        DELETE FROM fingerprint_merge_groups
        WHERE NOT EXISTS (
            SELECT 1
            FROM pattern_duplicate_candidates pdc
            WHERE pdc.candidate_key=fingerprint_merge_groups.candidate_key
        )
        """
    )
    conn.execute(
        """
        UPDATE fingerprint_merge_groups
        SET status=(
                SELECT pdc.status
                FROM pattern_duplicate_candidates pdc
                WHERE pdc.candidate_key=fingerprint_merge_groups.candidate_key
            ),
            canonical_fingerprint=COALESCE(
                (
                    SELECT fa.canonical_fingerprint
                    FROM fingerprint_aliases fa
                    WHERE fa.reason LIKE '%' || fingerprint_merge_groups.candidate_key || '%'
                    LIMIT 1
                ),
                canonical_fingerprint
            ),
            updated_at=CURRENT_TIMESTAMP
        WHERE EXISTS (
            SELECT 1
            FROM pattern_duplicate_candidates pdc
            WHERE pdc.candidate_key=fingerprint_merge_groups.candidate_key
        )
        """
    )
    conn.execute(
        """
        UPDATE fingerprint_merge_groups
        SET total_occurrence_count=COALESCE(
                (
                    SELECT fp.occurrence_count
                    FROM fingerprints fp
                    WHERE fp.fingerprint=fingerprint_merge_groups.canonical_fingerprint
                ),
                total_occurrence_count
            )
        WHERE status='approved'
        """
    )


def _fetch_fingerprint_merge_groups(
    conn: sqlite3.Connection, *, status: str = "pending", limit: int = 50
) -> list[dict[str, Any]]:
    _sync_fingerprint_merge_group_status(conn)
    params: list[Any] = []
    where_sql = ""
    if status:
        where_sql = "WHERE status=?"
        params.append(status)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT group_id, candidate_key, canonical_fingerprint, service_name,
               log_level, representative_template, member_fingerprints_json,
               avg_similarity, min_similarity, total_occurrence_count, status
        FROM fingerprint_merge_groups
        {where_sql}
        ORDER BY total_occurrence_count DESC, datetime(updated_at) DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "group_id": str(row[0]),
            "candidate_key": str(row[1]),
            "canonical_fingerprint": str(row[2]),
            "service_name": str(row[3]),
            "log_level": str(row[4]),
            "representative_template": str(row[5]),
            "member_fingerprints": [str(item) for item in _load_json_list(str(row[6]))],
            "avg_similarity": float(row[7] or 0),
            "min_similarity": float(row[8] or 0),
            "total_occurrence_count": int(row[9] or 0),
            "status": str(row[10]),
        }
        for row in rows
    ]


def _upsert_fingerprint_merge_groups(
    conn: sqlite3.Connection,
    *,
    candidates: list[dict[str, Any]],
    groups_by_fingerprint: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    merge_groups: list[dict[str, Any]] = []
    for candidate in candidates:
        fingerprints = [
            str(fp)
            for fp in candidate.get("fingerprints", [])
            if str(fp) in groups_by_fingerprint
        ]
        if len(fingerprints) < 2:
            continue
        canonical = max(
            fingerprints,
            key=lambda fp: int(groups_by_fingerprint[fp].get("occurrence_count") or 0),
        )
        total_count = sum(
            int(groups_by_fingerprint[fp].get("occurrence_count") or 0)
            for fp in fingerprints
        )
        similarity = float(candidate.get("confidence") or 0)
        group = {
            "group_id": _merge_group_id(str(candidate["candidate_key"])),
            "candidate_key": str(candidate["candidate_key"]),
            "canonical_fingerprint": canonical,
            "service_name": str(candidate.get("service_name") or ""),
            "log_level": str(candidate.get("log_level") or ""),
            "representative_template": str(candidate.get("suggested_template") or ""),
            "member_fingerprints": sorted(fingerprints),
            "avg_similarity": similarity,
            "min_similarity": similarity,
            "total_occurrence_count": total_count,
            "status": str(candidate.get("status") or "pending"),
        }
        conn.execute(
            """
            INSERT INTO fingerprint_merge_groups(
                group_id, candidate_key, canonical_fingerprint, service_name,
                log_level, representative_template, member_fingerprints_json,
                avg_similarity, min_similarity, total_occurrence_count, status,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(group_id) DO UPDATE SET
                canonical_fingerprint=excluded.canonical_fingerprint,
                service_name=excluded.service_name,
                log_level=excluded.log_level,
                representative_template=excluded.representative_template,
                member_fingerprints_json=excluded.member_fingerprints_json,
                avg_similarity=excluded.avg_similarity,
                min_similarity=excluded.min_similarity,
                total_occurrence_count=excluded.total_occurrence_count,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                group["group_id"],
                group["candidate_key"],
                group["canonical_fingerprint"],
                group["service_name"],
                group["log_level"],
                group["representative_template"],
                _json_list(group["member_fingerprints"]),
                group["avg_similarity"],
                group["min_similarity"],
                group["total_occurrence_count"],
                group["status"],
            ),
        )
        merge_groups.append(group)
    _sync_fingerprint_merge_group_status(conn)
    return merge_groups


def _window_id(service_name: str, bucket_start: str, bucket_size: str) -> str:
    raw = f"{service_name}|{bucket_start}|{bucket_size}"
    return "ETW-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14].upper()


def _vector_id(scope_key: str, bucket_start: str, bucket_size: str, version: str) -> str:
    raw = f"{scope_key}|{bucket_start}|{bucket_size}|{version}"
    return "SSV-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14].upper()


def _upsert_event_time_windows(
    conn: sqlite3.Connection, *, service_name: str | None
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE pt.service_name=?"
        params.append(service_name)
    rows = conn.execute(
        f"""
        SELECT
            pt.service_name, pt.bucket_start, pt.bucket_size,
            SUM(pt.total_count), SUM(pt.error_count), SUM(pt.warn_count),
            SUM(pt.info_count), COUNT(DISTINCT pt.fingerprint),
            SUM(CASE WHEN COALESCE(lar.is_known_pattern, 0)=1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN COALESCE(lar.is_new_pattern, 0)=1 THEN 1 ELSE 0 END),
            SUM(CASE WHEN COALESCE(ar.anomaly_detected, 0)=1 THEN 1 ELSE 0 END),
            MAX(COALESCE(ie.risk_score, 0))
        FROM pattern_time_series_metrics pt
        LEFT JOIN log_analysis_results lar ON lar.fingerprint=pt.fingerprint
        LEFT JOIN anomaly_results ar ON ar.fingerprint=pt.fingerprint
        LEFT JOIN impact_evaluations ie ON ie.fingerprint=pt.fingerprint
        {where}
        GROUP BY pt.service_name, pt.bucket_start, pt.bucket_size
        ORDER BY pt.bucket_size, pt.bucket_start DESC
        """,
        params,
    ).fetchall()
    windows: list[dict[str, Any]] = []
    for row in rows:
        svc = str(row[0] or "")
        bucket_start = str(row[1] or "")
        bucket_size = str(row[2] or "")
        top_rows = conn.execute(
            """
            SELECT fingerprint, total_count
            FROM pattern_time_series_metrics
            WHERE service_name=? AND bucket_start=? AND bucket_size=?
            ORDER BY total_count DESC, fingerprint ASC
            LIMIT 5
            """,
            (svc, bucket_start, bucket_size),
        ).fetchall()
        top_fingerprints = [
            {"fingerprint": str(fp), "count": int(count or 0)}
            for fp, count in top_rows
        ]
        window = {
            "window_id": _window_id(svc, bucket_start, bucket_size),
            "service_name": svc,
            "bucket_start": bucket_start,
            "bucket_size": bucket_size,
            "total_events": int(row[3] or 0),
            "error_events": int(row[4] or 0),
            "warn_events": int(row[5] or 0),
            "info_events": int(row[6] or 0),
            "unique_fingerprints": int(row[7] or 0),
            "known_fingerprint_count": int(row[8] or 0),
            "new_fingerprint_count": int(row[9] or 0),
            "anomaly_count": int(row[10] or 0),
            "max_risk_score": int(row[11] or 0),
            "top_fingerprints": top_fingerprints,
        }
        conn.execute(
            """
            INSERT INTO event_time_windows(
                window_id, service_name, bucket_start, bucket_size,
                total_events, error_events, warn_events, info_events,
                unique_fingerprints, known_fingerprint_count, new_fingerprint_count,
                anomaly_count, max_risk_score, top_fingerprints_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(service_name, bucket_start, bucket_size) DO UPDATE SET
                total_events=excluded.total_events,
                error_events=excluded.error_events,
                warn_events=excluded.warn_events,
                info_events=excluded.info_events,
                unique_fingerprints=excluded.unique_fingerprints,
                known_fingerprint_count=excluded.known_fingerprint_count,
                new_fingerprint_count=excluded.new_fingerprint_count,
                anomaly_count=excluded.anomaly_count,
                max_risk_score=excluded.max_risk_score,
                top_fingerprints_json=excluded.top_fingerprints_json,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                window["window_id"],
                window["service_name"],
                window["bucket_start"],
                window["bucket_size"],
                window["total_events"],
                window["error_events"],
                window["warn_events"],
                window["info_events"],
                window["unique_fingerprints"],
                window["known_fingerprint_count"],
                window["new_fingerprint_count"],
                window["anomaly_count"],
                window["max_risk_score"],
                _json_list(top_fingerprints),
            ),
        )
        windows.append(window)
    return windows


def _state_vector_from_window(window: dict[str, Any]) -> dict[str, Any]:
    total = max(1, int(window.get("total_events") or 0))
    unique = int(window.get("unique_fingerprints") or 0)
    features = {
        "total_events": int(window.get("total_events") or 0),
        "error_ratio": round(int(window.get("error_events") or 0) / total, 6),
        "warn_ratio": round(int(window.get("warn_events") or 0) / total, 6),
        "info_ratio": round(int(window.get("info_events") or 0) / total, 6),
        "unique_fingerprint_count": unique,
        "unique_fingerprint_ratio": round(unique / total, 6),
        "known_fingerprint_ratio": round(
            int(window.get("known_fingerprint_count") or 0) / max(1, unique), 6
        ),
        "new_fingerprint_ratio": round(
            int(window.get("new_fingerprint_count") or 0) / max(1, unique), 6
        ),
        "anomaly_count": int(window.get("anomaly_count") or 0),
        "max_risk_score": int(window.get("max_risk_score") or 0),
    }
    vector = [
        float(features["total_events"]),
        float(features["error_ratio"]),
        float(features["warn_ratio"]),
        float(features["info_ratio"]),
        float(features["unique_fingerprint_count"]),
        float(features["unique_fingerprint_ratio"]),
        float(features["known_fingerprint_ratio"]),
        float(features["new_fingerprint_ratio"]),
        float(features["anomaly_count"]),
        float(features["max_risk_score"]) / 100.0,
    ]
    return {"features": features, "vector": vector}


def _upsert_system_state_vectors(
    conn: sqlite3.Connection, *, windows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    version = "system-state-v1"
    vectors: list[dict[str, Any]] = []
    for window in windows:
        scope_key = str(window.get("service_name") or "all")
        state = _state_vector_from_window(window)
        label = (
            "incident"
            if int(window.get("anomaly_count") or 0) > 0
            else "warning"
            if int(window.get("max_risk_score") or 0) >= 70
            else "normal"
        )
        vector = {
            "vector_id": _vector_id(
                scope_key,
                str(window["bucket_start"]),
                str(window["bucket_size"]),
                version,
            ),
            "scope_key": scope_key,
            "service_name": str(window.get("service_name") or ""),
            "bucket_start": str(window.get("bucket_start") or ""),
            "bucket_size": str(window.get("bucket_size") or ""),
            "feature_schema_version": version,
            "features": state["features"],
            "vector": state["vector"],
            "label": label,
            "incident_id": "",
        }
        conn.execute(
            """
            INSERT INTO system_state_vectors(
                vector_id, scope_key, service_name, bucket_start, bucket_size,
                feature_schema_version, features_json, vector_json, label,
                incident_id, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(scope_key, bucket_start, bucket_size, feature_schema_version)
            DO UPDATE SET
                features_json=excluded.features_json,
                vector_json=excluded.vector_json,
                label=excluded.label,
                incident_id=excluded.incident_id,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                vector["vector_id"],
                vector["scope_key"],
                vector["service_name"],
                vector["bucket_start"],
                vector["bucket_size"],
                vector["feature_schema_version"],
                _json_dict(vector["features"]),
                _json_list(vector["vector"]),
                vector["label"],
                vector["incident_id"],
            ),
        )
        vectors.append(vector)
    return vectors


def _upsert_anomaly_daily_count(
    conn: sqlite3.Connection,
    *,
    service_name: str,
    analysis_date: str,
    anomaly_count: int,
) -> None:
    conn.execute(
        """
        INSERT INTO anomaly_daily_counts(
            service_name, analysis_date, anomaly_count, created_at, updated_at
        )
        VALUES (?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        ON CONFLICT(service_name, analysis_date) DO UPDATE SET
            anomaly_count=excluded.anomaly_count,
            updated_at=CURRENT_TIMESTAMP
        """,
        (service_name, analysis_date, anomaly_count),
    )


def fetch_anomaly_daily_counts(
    service_name: str = "", *, limit: int = 30
) -> list[dict[str, Any]]:
    """Return recent persisted anomaly counts grouped by analysis date."""
    db_path = _resolve_db_path()
    if not Path(db_path).exists():
        return []
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        params: list[Any] = []
        where = ""
        if service_name:
            where = "WHERE service_name=?"
            params.append(service_name)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT service_name, analysis_date, anomaly_count
            FROM anomaly_daily_counts
            {where}
            ORDER BY analysis_date DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "service_name": str(row[0]),
            "analysis_date": str(row[1]),
            "anomaly_count": int(row[2] or 0),
        }
        for row in reversed(rows)
    ]


def _metric_trend(metric: dict[str, Any]) -> str:
    latest = int(metric.get("latest_count") or 0)
    baseline = float(metric.get("baseline_count") or 0)
    if baseline >= 1 and latest == 0:
        return "absence"
    if baseline >= 1 and latest >= baseline * 2:
        return "increase"
    if baseline >= 4 and latest <= baseline * 0.5:
        return "decrease"
    return "stable"


def _anomaly_type_for(
    *,
    group: dict[str, Any],
    known: bool,
    spike_ratio: float,
    metric: dict[str, Any],
) -> tuple[bool, str, str]:
    status = str(group.get("pattern_status") or "")
    trend = _metric_trend(metric)
    if status == "new_pattern":
        return (
            True,
            "NEW_ERROR" if group.get("log_level") == "ERROR" else "NEW_PATTERN",
            "HIGH",
        )
    if status == "known_similar":
        return False, "NONE", "NONE"
    if known and group.get("previous_last_seen") and group.get("first_seen"):
        try:
            previous = datetime.fromisoformat(
                str(group["previous_last_seen"]).replace("Z", "+00:00")
            )
            current = datetime.fromisoformat(
                str(group["first_seen"]).replace("Z", "+00:00")
            )
            if current - previous >= timedelta(days=1):
                return True, "RECURRENCE", "MEDIUM"
        except ValueError:
            pass
    if trend == "absence":
        return True, "ABSENCE", "MEDIUM"
    if trend == "increase":
        return True, "SPIKE", "HIGH"
    if trend == "decrease":
        return True, "DROP", "MEDIUM"
    return False, "NONE", "NONE"


def _load_fingerprint_groups(
    conn: sqlite3.Connection, service_name: str | None
) -> dict[str, dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE fp.service_name=?"
        params.append(service_name)
    rows = conn.execute(
        f"""
        SELECT
            fp.fingerprint, fp.occurrence_count, fp.log_level, fp.message,
            fp.stacktrace, fp.service_name, fp.first_seen, fp.last_seen,
            COALESCE(lar.pattern_status, 'observed_existing'),
            COALESCE(lar.match_source, ''),
            COALESCE(lar.similar_fingerprint, ''),
            lar.similarity_score
        FROM fingerprints fp
        LEFT JOIN log_analysis_results lar ON lar.fingerprint = fp.fingerprint
        {where}
        """,
        params,
    ).fetchall()
    return {
        str(row[0]): {
            "fingerprint": str(row[0]),
            "occurrence_count": int(row[1] or 0),
            "log_level": str(row[2] or "").upper(),
            "message": str(row[3] or ""),
            "normalized_message": normalize_log_text(str(row[3] or "")),
            "stacktrace": str(row[4] or ""),
            "service_name": str(row[5] or ""),
            "first_seen": str(row[6] or ""),
            "last_seen": str(row[7] or ""),
            "pattern_status": str(row[8] or "observed_existing"),
            "match_source": str(row[9] or ""),
            "similar_fingerprint": str(row[10] or ""),
            "similarity_score": row[11],
        }
        for row in rows
    }


def _repair_approved_duplicate_candidates(
    conn: sqlite3.Connection, service_name: str | None
) -> int:
    rows = conn.execute(
        """
        SELECT candidate_key, service_name, log_level, fingerprints_json,
               suggested_regex, suggested_template
        FROM pattern_duplicate_candidates
        WHERE status='approved'
        """
    ).fetchall()
    repaired = 0
    for row in rows:
        candidate_key = str(row[0])
        candidate_service = str(row[1] or "")
        log_level = str(row[2] or "").upper()
        if service_name and candidate_service != service_name:
            continue
        fingerprints = [str(item) for item in _load_json_list(str(row[3] or "[]"))]
        suggested_regex = str(row[4] or "")
        suggested_template = str(row[5] or "")
        if not candidate_service or not log_level or not suggested_regex:
            continue
        try:
            matcher = re.compile(suggested_regex, flags=re.IGNORECASE)
        except re.error:
            continue
        log_rows = conn.execute(
            """
            SELECT rowid, service_name, level, message, COALESCE(stack_trace, ''), created_at
            FROM service_logs
            WHERE service_name=? AND upper(level)=?
            """,
            (candidate_service, log_level),
        ).fetchall()
        recalculated: dict[str, list[sqlite3.Row | tuple[Any, ...]]] = {}
        for log_row in log_rows:
            message = str(log_row[3] or "")
            if not matcher.search(message):
                continue
            new_fp = fingerprint_id(
                str(log_row[1]),
                str(log_row[2]).upper(),
                message,
                str(log_row[4] or ""),
            )
            recalculated.setdefault(new_fp, []).append(log_row)
        if not recalculated:
            continue
        canonical_fingerprint, canonical_rows = max(
            recalculated.items(), key=lambda item: len(item[1])
        )
        if len(canonical_rows) < 2:
            continue
        existing_known = conn.execute(
            """
            SELECT fingerprint
            FROM known_patterns
            WHERE cause=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (f"Approved duplicate pattern candidate {candidate_key}",),
        ).fetchone()
        previous_canonical = str(existing_known[0] or "") if existing_known else ""
        if previous_canonical:
            alias_count = conn.execute(
                f"""
                SELECT COUNT(*)
                FROM fingerprint_aliases
                WHERE canonical_fingerprint=?
                  AND old_fingerprint IN ({",".join("?" for _ in fingerprints)})
                """,
                [previous_canonical, *fingerprints],
            ).fetchone()[0]
            if int(alias_count or 0) > 0:
                continue
        if previous_canonical == canonical_fingerprint:
            continue

        occurrence_count = len(canonical_rows)
        first_seen = min(str(item[5] or "") for item in canonical_rows)
        last_seen = max(str(item[5] or "") for item in canonical_rows)
        representative = canonical_rows[0]
        normalized_stack = normalize_stacktrace(str(representative[4] or ""))
        conn.execute(
            """
            REPLACE INTO fingerprints(
                fingerprint, occurrence_count, log_level, message, stacktrace,
                service_name, first_seen, last_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_fingerprint,
                occurrence_count,
                log_level,
                suggested_template or str(representative[3] or ""),
                normalized_stack,
                candidate_service,
                first_seen,
                last_seen,
            ),
        )
        known_update = conn.execute(
            """
            UPDATE known_patterns
            SET fingerprint=?
            WHERE cause=?
            """,
            (
                canonical_fingerprint,
                f"Approved duplicate pattern candidate {candidate_key}",
            ),
        )
        if known_update.rowcount == 0:
            conn.execute(
                """
                INSERT INTO known_patterns(
                    fingerprint, category, sub_category, cause, recommendation, confidence
                ) VALUES (?, 'Manual', 'Merged Duplicate Pattern', ?, ?, 'HIGH')
                """,
                (
                    canonical_fingerprint,
                    f"Approved duplicate pattern candidate {candidate_key}",
                    "Pattern normalization rule groups duplicate fingerprints.",
                ),
            )
        alias_sources = set(fingerprints)
        if previous_canonical:
            alias_sources.add(previous_canonical)
        for old_fp in alias_sources:
            if old_fp == canonical_fingerprint:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO fingerprint_aliases(
                    old_fingerprint, canonical_fingerprint, reason, rule_id
                ) VALUES (
                    ?,
                    ?,
                    ?,
                    COALESCE((SELECT rule_id FROM fingerprint_aliases WHERE old_fingerprint=?), NULL)
                )
                """,
                (
                    old_fp,
                    canonical_fingerprint,
                    f"repaired approved duplicate candidate {candidate_key}",
                    old_fp,
                ),
            )
            conn.execute(
                "UPDATE processed_log_offsets SET fingerprint=? WHERE fingerprint=?",
                (canonical_fingerprint, old_fp),
            )
            conn.execute("DELETE FROM fingerprints WHERE fingerprint=?", (old_fp,))
            conn.execute("DELETE FROM log_analysis_results WHERE fingerprint=?", (old_fp,))
            conn.execute("DELETE FROM anomaly_results WHERE fingerprint=?", (old_fp,))
            conn.execute("DELETE FROM impact_evaluations WHERE fingerprint=?", (old_fp,))
        conn.execute(
            """
            INSERT OR REPLACE INTO log_analysis_results(
                fingerprint, category, sub_category, is_known_pattern,
                is_new_pattern, pattern_status, match_source,
                similar_fingerprint, similarity_score
            ) VALUES (?, 'Manual', 'Merged Duplicate Pattern', 1, 0, 'known_exact',
                      'known_patterns', '', NULL)
            """,
            (canonical_fingerprint,),
        )
        repaired += 1
    if repaired:
        _PIPELINE_CACHE.clear()
    return repaired


def run_detection_pipeline(
    service_name: str | None = None,
    *,
    days_back: int | None = None,
    analysis_date: str | None = None,
) -> dict[str, Any]:
    """Run SC-001~SC-005 over stored logs and return dashboard-ready summary data."""
    db_path = _resolve_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        _repair_approved_duplicate_candidates(conn, service_name)
        cur = conn.cursor()
        cutoff = (
            (datetime.utcnow() - timedelta(days=days_back)).isoformat(
                timespec="seconds"
            )
            if days_back is not None and analysis_date is None
            else None
        )
        date_start = None
        date_end = None
        if analysis_date:
            selected_date = datetime.fromisoformat(analysis_date).date()
            date_start = selected_date.isoformat()
        signature_count, signature_max_created = _pipeline_signature(
            conn, service_name, cutoff, date_start, date_end
        )
        last_rowid = _last_processed_rowid(conn, service_name)
        cache_key = (
            db_path,
            service_name,
            days_back,
            analysis_date,
            signature_count,
            0 if analysis_date else last_rowid,
            signature_max_created,
        )
        cached = _PIPELINE_CACHE.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)

        where_parts = []
        params: list[Any] = []
        if analysis_date is None:
            where_parts.append("rowid > ?")
            params.append(last_rowid)
        if service_name:
            where_parts.append("service_name=?")
            params.append(service_name)
        if cutoff:
            where_parts.append("created_at>=?")
            params.append(cutoff)
        if date_start:
            where_parts.append("substr(created_at, 1, 10)=?")
            params.append(date_start)
        where = f"WHERE {' AND '.join(where_parts)}"
        rows = cur.execute(
            f"""
            SELECT rowid, service_name, level, message, COALESCE(stack_trace,''), created_at
            FROM service_logs {where}
            ORDER BY rowid ASC
            """,
            params,
        ).fetchall()
        existing_fingerprints = {
            str(row[0])
            for row in cur.execute("SELECT fingerprint FROM fingerprints").fetchall()
        }
        known_signature_map = _known_pattern_signature_map(conn)
        groups: dict[str, dict[str, Any]] = {}
        max_rowid = last_rowid
        max_created = ""
        for rowid, svc, level, msg, stack, created in rows:
            max_rowid = max(max_rowid, int(rowid))
            max_created = max(max_created, str(created))
            normalized_message = normalize_log_text(msg)
            raw_fp = fingerprint_id(svc, level.upper(), msg, stack)
            fp = _canonical_fingerprint(
                conn,
                raw_fp,
                service_name=str(svc),
                log_level=str(level),
                message=str(msg or ""),
                known_signature_map=known_signature_map,
            )
            existing = cur.execute(
                """
                SELECT occurrence_count, first_seen, last_seen, message, stacktrace
                FROM fingerprints WHERE fingerprint=?
                """,
                (fp,),
            ).fetchone()
            item = groups.setdefault(
                fp,
                {
                    "fingerprint": fp,
                    "occurrence_count": (
                        0
                        if analysis_date
                        else int(existing[0] or 0)
                        if existing
                        else 0
                    ),
                    "log_level": level.upper(),
                    "message": (
                        msg
                        if analysis_date
                        else str(existing[3] or msg)
                        if existing
                        else msg
                    ),
                    "normalized_message": normalized_message,
                    "stacktrace": (
                        normalize_stacktrace(stack)
                        if analysis_date
                        else str(existing[4] or normalize_stacktrace(stack))
                        if existing
                        else normalize_stacktrace(stack)
                    ),
                    "service_name": svc,
                    "first_seen": (
                        created
                        if analysis_date
                        else str(existing[1] or created)
                        if existing
                        else created
                    ),
                    "last_seen": (
                        created
                        if analysis_date
                        else str(existing[2] or created)
                        if existing
                        else created
                    ),
                    "previous_last_seen": str(existing[2] or "") if existing else "",
                },
            )
            item["occurrence_count"] += 1
            item["first_seen"] = min(item["first_seen"], created)
            item["last_seen"] = max(item["last_seen"], created)
            cur.execute(
                """
                INSERT OR IGNORE INTO processed_log_offsets(service_name, log_rowid, fingerprint)
                VALUES (?, ?, ?)
                """,
                (svc, int(rowid), fp),
            )
            if cur.rowcount:
                for bucket_size in ("day", "hour"):
                    _increment_pattern_metric(
                        conn,
                        service_name=svc,
                        fingerprint=fp,
                        level=level,
                        created_at=created,
                        bucket_size=bucket_size,
                    )
        group_items = list(groups.values())
        group_contexts = [_pattern_cluster_context(item) for item in group_items]
        approved_match_groups = find_similar_analysis_documents_batch(
            queries=group_contexts
        )
        observed_match_groups = find_similar_pattern_clusters_batch(
            queries=group_contexts
        )
        for index, g in enumerate(group_items):
            approved_matches = (
                approved_match_groups[index]
                if index < len(approved_match_groups)
                else []
            )
            observed_matches = (
                observed_match_groups[index]
                if index < len(observed_match_groups)
                else []
            )
            g.update(
                _pattern_status_from_matches(
                    conn=conn,
                    item=g,
                    existing_fingerprints=existing_fingerprints,
                    approved_matches=approved_matches,
                    observed_matches=observed_matches,
                )
            )
        save_new_pattern_clusters(group_items)
        for g in group_items:
            cur.execute(
                "REPLACE INTO fingerprints VALUES (:fingerprint,:occurrence_count,:log_level,:message,:stacktrace,:service_name,:first_seen,:last_seen)",
                g,
            )
            cat, sub = classify(g["message"], g["stacktrace"])
            known = g["pattern_status"] in {"known_exact", "known_similar"}
            cur.execute(
                """
                REPLACE INTO log_analysis_results(
                    fingerprint, category, sub_category, is_known_pattern,
                    is_new_pattern, pattern_status, match_source,
                    similar_fingerprint, similarity_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    g["fingerprint"],
                    cat,
                    sub,
                    int(known),
                    int(g["pattern_status"] == "new_pattern"),
                    g["pattern_status"],
                    g["match_source"],
                    g["similar_fingerprint"],
                    g["similarity_score"],
                ),
            )
        if rows and analysis_date is None:
            _save_processing_state(conn, service_name, max_rowid, max_created)

        all_groups = groups if analysis_date else _load_fingerprint_groups(conn, service_name)
        ignored = {
            r[0]
            for r in cur.execute(
                "SELECT fingerprint FROM exception_registry"
            ).fetchall()
        }
        ignored_signatures = set()
        for row in cur.execute("""
            SELECT
                er.normalized_message,
                er.log_level,
                er.message,
                fp.message,
                fp.log_level
            FROM exception_registry er
            LEFT JOIN fingerprints fp ON fp.fingerprint = er.fingerprint
            """).fetchall():
            normalized = str(row[0] or "")
            message = str(row[2] or row[3] or "")
            level = str(row[1] or row[4] or "").upper()
            if not normalized and message:
                normalized = normalize_log_text(message)
            if normalized and level:
                ignored_signatures.add((normalized, level))
        anomalies = []
        impacts = []
        recs = []
        for fp, g in all_groups.items():
            is_ignored = (
                fp in ignored
                or (
                    g["normalized_message"],
                    g["log_level"],
                )
                in ignored_signatures
            )
            cat, sub = classify(g["message"], g["stacktrace"])
            known = g["pattern_status"] in {"known_exact", "known_similar"}
            baseline = max(
                1,
                math.ceil(
                    g["occurrence_count"] / (3 if g["occurrence_count"] >= 25 else 1)
                ),
            )
            spike_ratio = round((g["occurrence_count"] / baseline) * 100, 1)
            metric = _metric_baseline(
                conn, service_name=g["service_name"], fingerprint=fp
            )
            anomaly, anomaly_type, severity = _anomaly_type_for(
                group=g, known=known, spike_ratio=spike_ratio, metric=metric
            )
            if is_ignored:
                anomaly = False
                anomaly_type = "IGNORED"
                severity = "NONE"
            cur.execute(
                "REPLACE INTO anomaly_results VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
                (
                    fp,
                    int(anomaly),
                    spike_ratio if anomaly else 0,
                    severity,
                    anomaly_type,
                ),
            )
            if anomaly and not _is_new_pattern_anomaly(g, anomaly_type):
                anomaly_item = {
                    "system": g["service_name"],
                    "severity": severity,
                    "pattern": fp,
                    "message": g["message"],
                    "spike_ratio": spike_ratio,
                    "anomaly_type": anomaly_type,
                    "metric": metric,
                }
                anomalies.append(anomaly_item)
            score = min(
                100,
                LEVEL_SCORE.get(g["log_level"], 5)
                + CRITICALITY_SCORE.get(
                    SERVICE_CRITICALITY.get(g["service_name"], "LOW"), 5
                )
                + min(20, g["occurrence_count"] // 5),
            )
            if is_ignored:
                score = 0
            level = risk_level(score)
            cur.execute(
                "REPLACE INTO impact_evaluations(fingerprint,risk_score,risk_level,detected,created_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
                (fp, score, level, int(score > 0)),
            )
            impacts.append(
                {
                    "fingerprint": fp,
                    "risk_score": score,
                    "risk_level": level,
                    "detected": score > 0,
                }
            )
            r = recommendation_for(conn, fp, sub)
            r.update(
                {
                    "fingerprint": fp,
                    "sub_category": sub,
                    "pattern_status": g["pattern_status"],
                    "match_source": g["match_source"],
                    "similar_fingerprint": g["similar_fingerprint"],
                    "similarity_score": g["similarity_score"],
                }
            )
            recs.append(r)
        conn.commit()
        total_logs = int(signature_count)
        exception_count = cur.execute(
            "SELECT COUNT(*) FROM exception_registry"
        ).fetchone()[0]
    visible_groups = []
    exception_excluded_logs = 0
    ignored_fingerprints = set(ignored)
    for fp, group in all_groups.items():
        if (
            fp in ignored
            or (
                group["normalized_message"],
                group["log_level"],
            )
            in ignored_signatures
        ):
            ignored_fingerprints.add(fp)
            exception_excluded_logs += int(group.get("occurrence_count") or 0)
            continue
        visible_groups.append(group)
    duplicate_candidates = detect_duplicate_pattern_candidates(visible_groups)
    with sqlite3.connect(db_path) as model_conn:
        ensure_schema(model_conn)
        _upsert_fingerprint_merge_groups(
            model_conn,
            candidates=duplicate_candidates,
            groups_by_fingerprint={str(g["fingerprint"]): g for g in visible_groups},
        )
        merge_groups = _fetch_fingerprint_merge_groups(
            model_conn, status="pending", limit=50
        )
        event_time_windows = _upsert_event_time_windows(
            model_conn, service_name=service_name
        )
        system_state_vectors = _upsert_system_state_vectors(
            model_conn, windows=event_time_windows
        )
        model_conn.commit()
    latest_event_time_windows = sorted(
        event_time_windows,
        key=lambda item: (str(item["bucket_size"]), str(item["bucket_start"])),
        reverse=True,
    )[:12]
    latest_system_state_vectors = sorted(
        system_state_vectors,
        key=lambda item: (str(item["bucket_size"]), str(item["bucket_start"])),
        reverse=True,
    )[:12]
    visible_impacts = [
        impact
        for impact in impacts
        if impact["fingerprint"] not in ignored_fingerprints
    ]
    visible_recs = [
        rec for rec in recs if rec["fingerprint"] not in ignored_fingerprints
    ]
    anomalies = [
        item for item in anomalies if item["pattern"] not in ignored_fingerprints
    ]
    known_count = sum(
        1
        for group in visible_groups
        if group["pattern_status"] in {"known_exact", "known_similar"}
    )
    new_count = sum(
        1 for group in visible_groups if group["pattern_status"] == "new_pattern"
    )
    top_impact = max(
        visible_impacts,
        key=lambda x: x["risk_score"],
        default={"risk_score": 0, "risk_level": "Low", "detected": False},
    )
    top_rec = (
        visible_recs[0]
        if visible_recs
        else {"cause": "-", "recommendation": "-", "confidence": "LOW"}
    )
    daily_analysis_date = date_start or datetime.utcnow().date().isoformat()
    if service_name:
        with sqlite3.connect(db_path) as daily_conn:
            ensure_schema(daily_conn)
            _upsert_anomaly_daily_count(
                daily_conn,
                service_name=service_name,
                analysis_date=daily_analysis_date,
                anomaly_count=len(anomalies),
            )
            daily_conn.commit()
    anomaly_daily_counts = fetch_anomaly_daily_counts(service_name)
    result = {
        "fingerprints": visible_groups,
        "anomalies": anomalies,
        "anomaly_daily_counts": anomaly_daily_counts,
        "impacts": visible_impacts,
        "recommendations": visible_recs,
        "recommendation": top_rec,
        "duplicate_pattern_candidates": duplicate_candidates,
        "fingerprint_merge_groups": merge_groups,
        "event_time_windows": latest_event_time_windows,
        "system_state_vectors": latest_system_state_vectors,
        "summary": {
            "total_logs": total_logs,
            "processed_new_logs": len(rows),
            "total_fingerprints": len(visible_groups),
            "known_patterns": known_count,
            "new_patterns": new_count,
            "anomalies_detected": len(anomalies),
            "exception_registered_count": exception_count,
            "exception_excluded_logs": exception_excluded_logs,
            "risk_score": top_impact["risk_score"],
            "risk_level": top_impact["risk_level"],
            "detection_status": "Detected" if anomalies else "Normal",
        },
    }
    _PIPELINE_CACHE[cache_key] = copy.deepcopy(result)
    return result


def merge_selected_fingerprints_as_known_pattern(
    *,
    service_name: str,
    fingerprints: list[str],
    cause: str,
    recommendation: str,
    confidence: str = "HIGH",
) -> dict[str, Any]:
    """Create an approved duplicate candidate from selected FPs and register it."""

    selected = sorted({str(fp).strip() for fp in fingerprints if str(fp).strip()})
    if len(selected) < 2:
        raise ValueError("At least two fingerprints are required.")
    placeholders = ",".join("?" for _ in selected)
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            f"""
            SELECT fingerprint, occurrence_count, log_level, message, stacktrace,
                   service_name, first_seen, last_seen
            FROM fingerprints
            WHERE fingerprint IN ({placeholders})
            """,
            selected,
        ).fetchall()
        if len(rows) != len(selected):
            found = {str(row[0]) for row in rows}
            missing = [fp for fp in selected if fp not in found]
            raise ValueError(f"Fingerprint not found: {', '.join(missing)}")
        services = {str(row[5] or "") for row in rows}
        levels = {str(row[2] or "").upper() for row in rows}
        if service_name and services != {service_name}:
            raise ValueError("Selected fingerprints must belong to the selected service.")
        if len(services) != 1 or len(levels) != 1:
            raise ValueError("Selected fingerprints must share one service and log level.")
        items = [
            {
                "fingerprint": str(row[0]),
                "occurrence_count": int(row[1] or 0),
                "log_level": str(row[2] or "").upper(),
                "message": str(row[3] or ""),
                "stacktrace": str(row[4] or ""),
                "service_name": str(row[5] or ""),
                "first_seen": str(row[6] or ""),
                "last_seen": str(row[7] or ""),
            }
            for row in rows
        ]
        representative = max(items, key=lambda item: int(item["occurrence_count"]))
        signature = _common_duplicate_signature(items)
        if not signature:
            signature = duplicate_candidate_signature(str(representative["message"]))
        candidate_key = _duplicate_candidate_key(
            str(representative["service_name"]),
            str(representative["log_level"]),
            f"manual:{signature}:{','.join(selected)}",
        )
        suggested_regex = _suggest_regex_from_duplicate_items(signature, items)
        suggested_template = _suggest_template_from_duplicate_signature(signature)
        conn.execute(
            """
            INSERT INTO pattern_duplicate_candidates(
                candidate_key, service_name, log_level, signature,
                fingerprints_json, suggested_regex, suggested_template,
                confidence, reason, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 0.99, ?, 'approved', CURRENT_TIMESTAMP)
            ON CONFLICT(candidate_key) DO UPDATE SET
                fingerprints_json=excluded.fingerprints_json,
                suggested_regex=excluded.suggested_regex,
                suggested_template=excluded.suggested_template,
                confidence=excluded.confidence,
                reason=excluded.reason,
                status='approved',
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                candidate_key,
                str(representative["service_name"]),
                str(representative["log_level"]),
                signature,
                _json_list(selected),
                suggested_regex,
                suggested_template,
                "Manually selected fingerprints were approved for canonical merge.",
            ),
        )
        conn.commit()

    clear_normalization_rule_cache()
    rule_id = save_pattern_normalization_rule(
        name=f"manual-merge:{candidate_key}",
        match_regex=suggested_regex,
        template=suggested_template,
        enabled=True,
        priority=140,
    )
    merge_result = merge_duplicate_pattern_candidate(candidate_key, rule_id=rule_id)
    if not merge_result.get("merged"):
        return {
            "status": "failed",
            "candidate_key": candidate_key,
            "rule_id": rule_id,
            "merge": merge_result,
        }
    canonical = str(merge_result["canonical_fingerprint"])
    pattern_id = save_known_pattern(
        fingerprint=canonical,
        category="Manual",
        sub_category="Known Pattern",
        cause=cause,
        recommendation=recommendation,
        confidence=confidence,
    )
    return {
        "status": "merged",
        "candidate_key": candidate_key,
        "rule_id": rule_id,
        "known_pattern_id": pattern_id,
        "canonical_fingerprint": canonical,
        "merge": merge_result,
    }


def _is_new_pattern_anomaly(group: dict[str, Any], anomaly_type: str) -> bool:
    return str(group.get("pattern_status") or "") == "new_pattern" or anomaly_type in {
        "NEW_ERROR",
        "NEW_PATTERN",
        "PRESENCE",
    }


def _case_card_context(conn: sqlite3.Connection, fingerprint: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT
            fp.message,
            fp.log_level,
            fp.service_name,
            fp.stacktrace,
            fp.occurrence_count,
            fp.first_seen,
            fp.last_seen,
            lar.category,
            lar.sub_category,
            ar.severity,
            ie.risk_score,
            ie.risk_level
        FROM fingerprints fp
        LEFT JOIN log_analysis_results lar ON lar.fingerprint = fp.fingerprint
        LEFT JOIN anomaly_results ar ON ar.fingerprint = fp.fingerprint
        LEFT JOIN impact_evaluations ie ON ie.fingerprint = fp.fingerprint
        WHERE fp.fingerprint = ?
        """,
        (fingerprint,),
    ).fetchone()
    if not row:
        return {
            "message": "",
            "log_level": "",
            "service_name": "",
            "stacktrace": "",
            "occurrence_count": 0,
            "first_seen": "",
            "last_seen": "",
            "category": "Unknown",
            "sub_category": "Unknown",
            "severity": "UNKNOWN",
            "risk_score": 0,
            "risk_level": "Low",
            "normalized_message": "",
        }
    message = str(row[0] or "")
    return {
        "message": message,
        "log_level": str(row[1] or ""),
        "service_name": str(row[2] or ""),
        "stacktrace": str(row[3] or ""),
        "occurrence_count": int(row[4] or 0),
        "first_seen": str(row[5] or ""),
        "last_seen": str(row[6] or ""),
        "category": str(row[7] or "Unknown"),
        "sub_category": str(row[8] or "Unknown"),
        "severity": str(row[9] or "UNKNOWN"),
        "risk_score": int(row[10] or 0),
        "risk_level": str(row[11] or "Low"),
        "normalized_message": normalize_log_text(message),
    }


def build_rag_case_card(
    *,
    card_id: str,
    fingerprint: str,
    cause: str,
    recommendation: str,
    action: str,
    confidence: str,
    context: dict[str, Any],
    resolution_method: str = "",
) -> dict[str, Any]:
    """Build a sectioned Case Card that can later be migrated into RAG chunks."""

    service_name = str(context.get("service_name") or "unknown-service")
    category = str(context.get("category") or "Unknown")
    sub_category = str(context.get("sub_category") or "Unknown")
    log_level = str(context.get("log_level") or "UNKNOWN")
    message = str(context.get("message") or "")
    normalized_message = str(context.get("normalized_message") or "")
    stacktrace = str(context.get("stacktrace") or "")
    occurrence_count = int(context.get("occurrence_count") or 0)
    title = f"{service_name} {sub_category} case ({fingerprint})"
    summary = (
        f"{service_name}에서 {sub_category} 패턴이 {occurrence_count}회 관측되었습니다."
    )
    symptoms = [
        f"{service_name} 서비스에서 {log_level} 로그가 발생했습니다.",
        f"동일 fingerprint({fingerprint})가 {occurrence_count}회 관측되었습니다.",
    ]
    if normalized_message:
        symptoms.append(f"정규화 메시지: {normalized_message}")
    evidence_lines = [
        f"Message: {message or '-'}",
        f"Normalized Message: {normalized_message or '-'}",
        f"Stack Trace: {stacktrace or '-'}",
    ]
    root_cause = cause or "원인 미상"
    resolution_method = resolution_method.strip()
    remediation_steps = [recommendation] if recommendation else []
    verification_steps = [
        f"{fingerprint} fingerprint 재발 여부를 확인합니다.",
        f"{service_name}의 error rate와 동일 로그 발생량이 감소했는지 확인합니다.",
    ]
    prevention_steps = [
        "동일 fingerprint 기반 알림 또는 Known Pattern 등록 여부를 검토합니다.",
        "조치 후 재발 시 원인/조치/검증 section을 업데이트합니다.",
    ]
    metadata = {
        "card_id": card_id,
        "fingerprint": fingerprint,
        "service_name": service_name,
        "log_level": log_level,
        "category": category,
        "sub_category": sub_category,
        "risk_score": int(context.get("risk_score") or 0),
        "risk_level": str(context.get("risk_level") or "Low"),
        "confidence": confidence,
        "action": action,
        "has_resolution_method": bool(resolution_method),
        "source": "approved_recommendation",
        "schema_version": "rag-case-card-v1",
        "chunk_ready": True,
    }
    rag_document = "\n".join(
        [
            "[Case Card]",
            f"Title: {title}",
            f"Fingerprint: {fingerprint}",
            f"Service: {service_name}",
            f"Category: {category} / {sub_category}",
            f"Confidence: {confidence}",
            f"Risk: {metadata['risk_level']} ({metadata['risk_score']})",
            "",
            "[Summary]",
            summary,
            "",
            "[Symptoms]",
            *[f"- {item}" for item in symptoms],
            "",
            "[Evidence]",
            *[f"- {item}" for item in evidence_lines],
            "",
            "[Root Cause]",
            root_cause,
            "",
            "[Recommendation]",
            *[f"- {item}" for item in remediation_steps],
            "",
            "[Resolution Method]",
            resolution_method or "-",
            "",
            "[Verification]",
            *[f"- {item}" for item in verification_steps],
            "",
            "[Prevention]",
            *[f"- {item}" for item in prevention_steps],
        ]
    )
    return {
        "title": title,
        "summary": summary,
        "symptoms": symptoms,
        "evidence_text": "\n".join(evidence_lines),
        "root_cause": root_cause,
        "resolution_method": resolution_method,
        "remediation_steps": remediation_steps,
        "verification_steps": verification_steps,
        "prevention_steps": prevention_steps,
        "metadata": metadata,
        "rag_document": rag_document,
    }


def fetch_knowledge_cards(
    *, fingerprint: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """Return approved Knowledge Cards, newest first."""
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        params: list[Any] = []
        where_sql = ""
        if fingerprint:
            where_sql = "WHERE kc.fingerprint = ?"
            params.append(fingerprint)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT
                kc.card_id,
                kc.fingerprint,
                kc.cause,
                kc.recommendation,
                kc.action,
                kc.confidence,
                kc.resolution_method,
                kc.created_at,
                COALESCE(fp.message, ''),
                COALESCE(fp.log_level, ''),
                COALESCE(fp.service_name, ''),
                kc.title,
                kc.summary,
                kc.symptoms,
                kc.evidence_text,
                kc.root_cause,
                kc.remediation_steps,
                kc.verification_steps,
                kc.prevention_steps,
                kc.metadata_json,
                kc.rag_document,
                kc.embedding_status
            FROM knowledge_cards kc
            LEFT JOIN fingerprints fp ON fp.fingerprint = kc.fingerprint
            {where_sql}
            ORDER BY datetime(kc.created_at) DESC, kc.card_id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "card_id": str(row[0]),
            "fingerprint": str(row[1]),
            "cause": str(row[2]),
            "recommendation": str(row[3]),
            "action": str(row[4]),
            "confidence": str(row[5]),
            "resolution_method": str(row[6]),
            "created_at": str(row[7]),
            "message": str(row[8]),
            "log_level": str(row[9]),
            "service_name": str(row[10]),
            "title": str(row[11]),
            "summary": str(row[12]),
            "symptoms": _load_json_list(str(row[13])),
            "evidence_text": str(row[14]),
            "root_cause": str(row[15]),
            "remediation_steps": _load_json_list(str(row[16])),
            "verification_steps": _load_json_list(str(row[17])),
            "prevention_steps": _load_json_list(str(row[18])),
            "metadata": _load_json_dict(str(row[19])),
            "rag_document": str(row[20]),
            "embedding_status": str(row[21]),
        }
        for row in rows
    ]


def fetch_known_patterns_for_agents(limit: int = 500) -> list[dict[str, str]]:
    """Return DB-backed known patterns in a shape agents can merge with config rules."""
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        rows = conn.execute(
            """
            SELECT id, fingerprint, category, sub_category, cause, recommendation, confidence
            FROM known_patterns
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "id": str(row[0]),
            "fingerprint": str(row[1] or ""),
            "category": str(row[2] or ""),
            "sub_category": str(row[3] or ""),
            "cause": str(row[4] or ""),
            "recommendation": str(row[5] or ""),
            "confidence": str(row[6] or ""),
        }
        for row in rows
    ]


def save_known_pattern(
    *,
    fingerprint: str,
    category: str,
    sub_category: str,
    cause: str,
    recommendation: str,
    confidence: str = "HIGH",
) -> int:
    """Persist a human-selected known pattern."""

    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO known_patterns(
                fingerprint, category, sub_category, cause, recommendation, confidence
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fingerprint,
                category,
                sub_category,
                cause,
                recommendation,
                confidence,
            ),
        )
        conn.commit()
        pattern_id = int(cur.lastrowid)
        row = conn.execute(
            """
            SELECT message, stacktrace, service_name, log_level
            FROM fingerprints
            WHERE fingerprint = ?
            """,
            (fingerprint,),
        ).fetchone()

    message = str(row[0] or "") if row else ""
    stacktrace = str(row[1] or "") if row else ""
    service_name = str(row[2] or "") if row else ""
    log_level = str(row[3] or "") if row else ""
    document = "\n".join(
        [
            "[Known Pattern]",
            f"Fingerprint: {fingerprint}",
            f"Service: {service_name or '-'}",
            f"Log Level: {log_level or '-'}",
            f"Category: {category} / {sub_category}",
            f"Cause: {cause}",
            f"Recommendation: {recommendation}",
            "",
            "[Evidence]",
            f"Message: {message or '-'}",
            f"Stack Trace: {stacktrace or '-'}",
        ]
    )
    save_analysis_document(
        doc_id=f"known-pattern:{pattern_id}",
        text=document,
        metadata={
            "source": "known_pattern",
            "fingerprint": fingerprint,
            "category": category,
            "sub_category": sub_category,
            "confidence": confidence,
            "schema_version": "known-pattern-v1",
        },
    )
    return pattern_id


def save_pattern_normalization_rule(
    *,
    name: str,
    match_regex: str,
    template: str,
    enabled: bool = True,
    priority: int = 100,
) -> int:
    """Persist an approved normalization rule used before generic fingerprinting."""

    re.compile(match_regex)
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO pattern_normalization_rules(
                name, match_regex, template, enabled, priority
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (name, match_regex, template, int(enabled), priority),
        )
        conn.commit()
        rule_id = int(cur.lastrowid)
    clear_normalization_rule_cache()
    _PIPELINE_CACHE.clear()
    return rule_id


def fetch_exception_registry(
    *, fingerprint: str | None = None, limit: int = 20
) -> list[dict[str, str]]:
    """Return registered exception fingerprints, newest first."""
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        params: list[Any] = []
        where_sql = ""
        if fingerprint:
            where_sql = "WHERE er.fingerprint = ?"
            params.append(fingerprint)
        params.append(limit)
        rows = conn.execute(
            f"""
            SELECT
                er.fingerprint,
                er.reason,
                er.created_at,
                COALESCE(NULLIF(er.message, ''), fp.message, ''),
                COALESCE(NULLIF(er.log_level, ''), fp.log_level, ''),
                COALESCE(NULLIF(er.service_name, ''), fp.service_name, '')
            FROM exception_registry er
            LEFT JOIN fingerprints fp ON fp.fingerprint = er.fingerprint
            {where_sql}
            ORDER BY datetime(er.created_at) DESC, er.fingerprint DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "fingerprint": str(row[0]),
            "reason": str(row[1]),
            "created_at": str(row[2]),
            "message": str(row[3]),
            "log_level": str(row[4]),
            "service_name": str(row[5]),
        }
        for row in rows
    ]


def register_exception(fp: str, reason: str) -> None:
    """Register a fingerprint that should be ignored by risk and anomaly detection."""
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        row = conn.execute(
            """
            SELECT message, log_level, service_name
            FROM fingerprints
            WHERE fingerprint = ?
            """,
            (fp,),
        ).fetchone()
        message = str(row[0]) if row else ""
        log_level = str(row[1]).upper() if row else ""
        service_name = str(row[2]) if row else ""
        conn.execute(
            """
            REPLACE INTO exception_registry(
                fingerprint, reason, message, log_level, service_name, normalized_message
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (fp, reason, message, log_level, service_name, normalize_log_text(message)),
        )
        conn.commit()


def approve_result(
    fp: str,
    cause: str,
    recommendation: str,
    action: str,
    confidence: str,
    resolution_method: str = "",
) -> str:
    """Persist an approved result as a RAG-ready, reusable Knowledge Card."""

    card_id = "KC-" + datetime.utcnow().strftime("%H%M%S%f")[:9]
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        context = _case_card_context(conn, fp)
        case_card = build_rag_case_card(
            card_id=card_id,
            fingerprint=fp,
            cause=cause,
            recommendation=recommendation,
            action=action,
            confidence=confidence,
            resolution_method=resolution_method,
            context=context,
        )
        metadata = case_card["metadata"]
        embedded = save_analysis_document(
            doc_id=f"knowledge-card:{card_id}",
            text=case_card["rag_document"],
            metadata=metadata,
        )
        embedding_status = "embedded" if embedded else "pending"
        conn.execute(
            """
            INSERT INTO knowledge_cards(
                card_id, fingerprint, cause, recommendation, action, confidence,
                resolution_method,
                title, summary, symptoms, evidence_text, root_cause, remediation_steps,
                verification_steps, prevention_steps, metadata_json, rag_document, embedding_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_id,
                fp,
                cause,
                recommendation,
                action,
                confidence,
                case_card["resolution_method"],
                case_card["title"],
                case_card["summary"],
                _json_list(case_card["symptoms"]),
                case_card["evidence_text"],
                case_card["root_cause"],
                _json_list(case_card["remediation_steps"]),
                _json_list(case_card["verification_steps"]),
                _json_list(case_card["prevention_steps"]),
                _json_dict(metadata),
                case_card["rag_document"],
                embedding_status,
            ),
        )
        conn.commit()
    return card_id
