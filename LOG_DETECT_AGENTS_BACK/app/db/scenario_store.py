"""Scenario database pipeline for log fingerprinting, detection, risk, and knowledge reuse."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import math
import re
import sqlite3
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from drain3 import TemplateMiner
from drain3.template_miner_config import TemplateMinerConfig

from app.db.chroma_store import (
    delete_pattern_clusters,
    embed_pattern_texts_normalized,
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
PATTERN_KNOWN_SIMILARITY_THRESHOLD = 0.88
PATTERN_DUPLICATE_SIMILARITY_THRESHOLD = 0.92
PATTERN_WEIGHTS = {
    "drain_template": 0.30,
    "fixed_token_lexical": 0.25,
    "sequence_structure": 0.15,
    "key_value_schema": 0.10,
    "metadata": 0.10,
    "stacktrace": 0.05,
    "embedding": 0.05,
}
HYBRID_KNOWN_SIMILARITY_THRESHOLD = PATTERN_KNOWN_SIMILARITY_THRESHOLD
HYBRID_DUPLICATE_SIMILARITY_THRESHOLD = PATTERN_DUPLICATE_SIMILARITY_THRESHOLD
HYBRID_WEIGHTS = PATTERN_WEIGHTS
HYBRID_VECTOR_SCHEMA_VERSION = "hybrid-event-v1"
HYBRID_HASH_DIMENSIONS = 32
HYBRID_TEXT_WEIGHT = 0.75
HYBRID_CATEGORICAL_WEIGHT = 0.15
HYBRID_NUMERIC_WEIGHT = 0.10
HYBRID_NO_TEXT_CATEGORICAL_WEIGHT = 0.65
HYBRID_NO_TEXT_NUMERIC_WEIGHT = 0.35
HDBSCAN_MIN_CLUSTER_SIZE = 3
HDBSCAN_MIN_SAMPLES = 2
HDBSCAN_MAX_DISTANCE = 1.0 - PATTERN_DUPLICATE_SIMILARITY_THRESHOLD
RECURRENCE_MIN_SILENCE_DAYS = 7
SEMANTIC_CLUSTER_MIN_CLUSTER_SIZE = 3
SEMANTIC_CLUSTER_MIN_SAMPLES = 2
PATTERN_CLUSTER_MEMBER_THRESHOLD = 0.88
PATTERN_CLUSTER_HYBRID_PATTERN_THRESHOLD = 0.82
PATTERN_CLUSTER_SEMANTIC_LINK_THRESHOLD = 0.85
PATTERN_CLUSTER_HYBRID_PATTERN_WEIGHT = 0.70
PATTERN_CLUSTER_HYBRID_SEMANTIC_WEIGHT = 0.30
PATTERN_CLUSTER_MAX_LINKS_PER_CLUSTER = 5
TIME_WINDOW_RECENT_RECALC_LIMIT = 200
TIME_WINDOW_RETURN_LIMIT = 24
TRAJECTORY_FIXED_WINDOW_LENGTH = 6
TRAJECTORY_RETURN_LIMIT = 12
TRAJECTORY_CLUSTER_RETURN_LIMIT = 8
TRAJECTORY_NEAREST_RETURN_LIMIT = 3
TRAJECTORY_CLUSTER_MIN_SIZE = 3
TRAJECTORY_CLUSTER_MIN_SAMPLES = 2
TIME_SERIES_BUCKET_SIZES = ("day", "hour", "30min")


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


def drain_log_template(value: str) -> str:
    """Build a fallback event template for single-message callers.

    Real Drain3 mining is intentionally kept in _apply_drain_templates() so
    TemplateMiner is created once per batch instead of once per log row.
    """

    return _fallback_drain_template(value)


def _drain_input(value: str) -> str:
    text = _apply_normalization_rules(value or "")
    text = EXCEL_NEWLINE_RE.sub(" ", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def _fallback_drain_template(value: str) -> str:
    """Fallback used only when the Drain3 package is not available."""

    template = normalize_log_text(value)
    template = re.sub(r'"?\*"?', "<*>", template)
    template = re.sub(r"\b[a-f0-9]{8,}\b", "<*>", template, flags=re.IGNORECASE)
    template = re.sub(r"\s+", " ", template)
    return template.strip()


def _drain3_template_miner() -> Any | None:
    try:
        from drain3 import TemplateMiner
        from drain3.template_miner_config import TemplateMinerConfig
    except Exception:  # noqa: BLE001
        return None
    config = TemplateMinerConfig()
    return TemplateMiner(config=config)


def _mine_drain_templates(messages: list[str]) -> list[str]:
    if not messages:
        return []
    miner = _drain3_template_miner()
    if miner is None:
        return [_fallback_drain_template(message) for message in messages]

    prepared = [_drain_input(message) for message in messages]
    for message in prepared:
        if message:
            miner.add_log_message(message)

    templates: list[str] = []
    for message in prepared:
        if not message:
            templates.append("")
            continue
        result = miner.add_log_message(message)
        templates.append(str(result.get("template_mined") or message))
    return templates


def _apply_drain_templates(groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not groups:
        return []

    enriched = [dict(group) for group in groups]
    missing_indexes = [
        index
        for index, group in enumerate(enriched)
        if not str(group.get("drain_template") or "").strip()
    ]
    if not missing_indexes:
        return enriched

    templates = _mine_drain_templates(
        [str(enriched[index].get("message") or "") for index in missing_indexes]
    )
    for offset, index in enumerate(missing_indexes):
        message = str(enriched[index].get("message") or "")
        enriched[index]["drain_template"] = (
            templates[offset]
            if offset < len(templates) and templates[offset]
            else _fallback_drain_template(message)
        )
    return enriched


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
        CREATE TABLE IF NOT EXISTS pattern_clusters (
            cluster_id TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            log_level TEXT NOT NULL,
            canonical_fingerprint TEXT NOT NULL,
            representative_template TEXT NOT NULL,
            representative_message TEXT NOT NULL DEFAULT '',
            algorithm TEXT NOT NULL,
            member_count INTEGER NOT NULL DEFAULT 0,
            total_occurrence_count INTEGER NOT NULL DEFAULT 0,
            avg_pattern_similarity REAL NOT NULL DEFAULT 0,
            min_pattern_similarity REAL NOT NULL DEFAULT 0,
            avg_semantic_similarity REAL NOT NULL DEFAULT 0,
            max_semantic_similarity REAL NOT NULL DEFAULT 0,
            known_status TEXT NOT NULL DEFAULT '',
            hybrid_vector_json TEXT NOT NULL DEFAULT '[]',
            hybrid_vector_schema_version TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pattern_cluster_members (
            cluster_id TEXT NOT NULL,
            fingerprint TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',
            pattern_similarity REAL NOT NULL DEFAULT 0,
            semantic_similarity REAL NOT NULL DEFAULT 0,
            hybrid_score REAL NOT NULL DEFAULT 0,
            match_type TEXT NOT NULL DEFAULT 'pattern_match',
            occurrence_count INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(cluster_id, fingerprint)
        );
        CREATE TABLE IF NOT EXISTS pattern_cluster_links (
            source_cluster_id TEXT NOT NULL,
            target_cluster_id TEXT NOT NULL,
            pattern_similarity REAL NOT NULL DEFAULT 0,
            semantic_similarity REAL NOT NULL DEFAULT 0,
            hybrid_score REAL NOT NULL DEFAULT 0,
            link_type TEXT NOT NULL DEFAULT 'semantic_match',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(source_cluster_id, target_cluster_id)
        );
        CREATE TABLE IF NOT EXISTS semantic_log_clusters (
            cluster_id TEXT PRIMARY KEY,
            analysis_date TEXT NOT NULL,
            service_name TEXT NOT NULL,
            log_level TEXT NOT NULL DEFAULT '',
            algorithm TEXT NOT NULL,
            representative_fingerprint TEXT NOT NULL DEFAULT '',
            representative_log TEXT NOT NULL DEFAULT '',
            representative_cause TEXT NOT NULL DEFAULT '',
            recommendation_hint TEXT NOT NULL DEFAULT '',
            drain_template TEXT NOT NULL DEFAULT '',
            fingerprints_json TEXT NOT NULL DEFAULT '[]',
            pattern_statuses_json TEXT NOT NULL DEFAULT '[]',
            count INTEGER NOT NULL DEFAULT 0,
            fingerprint_count INTEGER NOT NULL DEFAULT 0,
            risk_score INTEGER NOT NULL DEFAULT 0,
            anomaly_count INTEGER NOT NULL DEFAULT 0,
            evidence_schema_version TEXT NOT NULL DEFAULT 'semantic-log-cluster-v1',
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
        CREATE TABLE IF NOT EXISTS trajectories (
            trajectory_id TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            bucket_size TEXT NOT NULL,
            window_length INTEGER NOT NULL,
            start_bucket TEXT NOT NULL,
            end_bucket TEXT NOT NULL,
            vector_ids_json TEXT NOT NULL,
            top_fingerprints_json TEXT NOT NULL DEFAULT '[]',
            features_json TEXT NOT NULL DEFAULT '{}',
            flat_vector_json TEXT NOT NULL DEFAULT '[]',
            label TEXT NOT NULL DEFAULT '',
            max_risk_score INTEGER NOT NULL DEFAULT 0,
            anomaly_count INTEGER NOT NULL DEFAULT 0,
            total_events INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(service_name, bucket_size, window_length, start_bucket, end_bucket)
        );
        CREATE TABLE IF NOT EXISTS trajectory_clusters (
            cluster_id TEXT PRIMARY KEY,
            service_name TEXT NOT NULL,
            bucket_size TEXT NOT NULL,
            algorithm TEXT NOT NULL,
            representative_trajectory_id TEXT NOT NULL,
            member_trajectory_ids_json TEXT NOT NULL,
            top_fingerprints_json TEXT NOT NULL DEFAULT '[]',
            label TEXT NOT NULL DEFAULT '',
            member_count INTEGER NOT NULL DEFAULT 0,
            max_risk_score INTEGER NOT NULL DEFAULT 0,
            anomaly_count INTEGER NOT NULL DEFAULT 0,
            avg_distance REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_ptsm_service_bucket
            ON pattern_time_series_metrics(service_name, bucket_size, bucket_start);
        CREATE INDEX IF NOT EXISTS idx_ptsm_window_top
            ON pattern_time_series_metrics(
                service_name, bucket_start, bucket_size, total_count DESC
            );
        CREATE INDEX IF NOT EXISTS idx_event_windows_service_bucket
            ON event_time_windows(service_name, bucket_size, bucket_start DESC);
        CREATE INDEX IF NOT EXISTS idx_state_vectors_service_bucket
            ON system_state_vectors(service_name, bucket_size, bucket_start DESC);
        CREATE INDEX IF NOT EXISTS idx_pattern_clusters_service_level
            ON pattern_clusters(service_name, log_level, member_count DESC);
        CREATE INDEX IF NOT EXISTS idx_pattern_cluster_members_fingerprint
            ON pattern_cluster_members(fingerprint);
        CREATE INDEX IF NOT EXISTS idx_pattern_cluster_links_target
            ON pattern_cluster_links(target_cluster_id, semantic_similarity DESC);
        CREATE INDEX IF NOT EXISTS idx_semantic_log_clusters_service_date
            ON semantic_log_clusters(service_name, analysis_date, risk_score DESC);
        CREATE INDEX IF NOT EXISTS idx_semantic_log_clusters_representative
            ON semantic_log_clusters(representative_fingerprint);
        CREATE INDEX IF NOT EXISTS idx_trajectories_service_bucket
            ON trajectories(service_name, bucket_size, end_bucket DESC);
        CREATE INDEX IF NOT EXISTS idx_trajectory_clusters_service_bucket
            ON trajectory_clusters(service_name, bucket_size, member_count DESC);
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
    for column, definition in {
        "hybrid_vector_json": "TEXT NOT NULL DEFAULT '[]'",
        "hybrid_vector_schema_version": "TEXT NOT NULL DEFAULT ''",
    }.items():
        pattern_cluster_columns = [
            row[1]
            for row in cur.execute("PRAGMA table_info(pattern_clusters)").fetchall()
        ]
        if column not in pattern_cluster_columns:
            cur.execute(f"ALTER TABLE pattern_clusters ADD COLUMN {column} {definition}")
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
            f"drain_template={item.get('drain_template') or item.get('normalized_message', '')}",
            f"normalized_message={item.get('normalized_message', '')}",
            f"context={item.get('stacktrace') or item.get('message') or ''}",
        ]
    )


def _metadata_from_match(match: dict[str, Any]) -> dict[str, Any]:
    metadata = match.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _fingerprint_from_match(match: dict[str, Any]) -> str:
    metadata = _metadata_from_match(match)
    fingerprint = str(metadata.get("fingerprint") or match.get("id") or "")
    if ":" in fingerprint:
        fingerprint = fingerprint.rsplit(":", 1)[-1]
    return fingerprint


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9_./:-]+", normalize_log_text(text).lower()))


def _token_list(text: str) -> list[str]:
    return re.findall(r"[a-z0-9_./:-]+", normalize_log_text(text).lower())


def _sequence_similarity(left: str, right: str) -> float:
    left_norm = normalize_log_text(left)
    right_norm = normalize_log_text(right)
    if not left_norm and not right_norm:
        return 1.0
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _jaccard_similarity(left: str, right: str) -> float:
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens and not right_tokens:
        return 1.0
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _template_structure(text: str) -> str:
    normalized = normalize_log_text(text)
    normalized = re.sub(r"\b[a-z_][\w.-]*\s*[:=]\s*<[^>\s]+>", "key=<value>", normalized)
    normalized = re.sub(r"<[^>\s]+>", "<value>", normalized)
    normalized = re.sub(r"[a-z]+", "a", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _drain_template_miner() -> TemplateMiner:
    config = TemplateMinerConfig()
    config.profiling_enabled = False
    config.drain_depth = 4
    config.drain_sim_th = 0.4
    config.drain_max_children = 100
    return TemplateMiner(config=config)


def _drain_template(text: str) -> str:
    normalized = normalize_log_text(text).lower()
    result = _drain_template_miner().add_log_message(normalized)
    template = str(result.get("template_mined") or "").strip()
    return template or normalized.strip()


def _drain_template_similarity(left: str, right: str) -> float:
    left_normalized = normalize_log_text(left).lower()
    right_normalized = normalize_log_text(right).lower()
    if not left_normalized and not right_normalized:
        return 0.0
    miner = _drain_template_miner()
    left_result = miner.add_log_message(left_normalized)
    right_result = miner.add_log_message(right_normalized)
    left_template = str(left_result.get("template_mined") or left_normalized).strip()
    right_template = str(right_result.get("template_mined") or right_normalized).strip()
    if left_template == right_template:
        return 1.0
    same_cluster_bonus = 0.1 if left_result.get("cluster_id") == right_result.get("cluster_id") else 0.0
    return min(1.0, _sequence_similarity(left_template, right_template) + same_cluster_bonus)


def _template_structure_similarity(left: str, right: str) -> float:
    return _sequence_similarity(_template_structure(left), _template_structure(right))


def _key_value_schema(text: str) -> set[str]:
    keys = {
        match.group(1).lower()
        for match in re.finditer(r"\b([a-zA-Z_][\w.-]*)\s*[:=]\s*", text)
    }
    keys.update(
        match.group(1).lower()
        for match in re.finditer(r"\b([a-zA-Z_][\w.-]*)\s+\*", normalize_log_text(text))
    )
    return keys


def _key_value_schema_similarity(left: str, right: str) -> float:
    left_keys = _key_value_schema(left)
    right_keys = _key_value_schema(right)
    if not left_keys and not right_keys:
        return 0.0
    if not left_keys or not right_keys:
        return 0.0
    return len(left_keys & right_keys) / len(left_keys | right_keys)


def _fixed_tokens(text: str) -> list[str]:
    tokens = _token_list(text)
    variable_tokens = {"*", "value", "number", "uuid", "timestamp", "id"}
    fixed: list[str] = []
    for token in tokens:
        stripped = token.strip("*<>").lower()
        if not stripped or stripped in variable_tokens:
            continue
        if stripped.isdigit():
            continue
        if len(stripped) <= 1:
            continue
        fixed.append(stripped)
    return fixed


def _bm25_pair_similarity(left: str, right: str) -> float:
    query_tokens = _fixed_tokens(left)
    document_tokens = _fixed_tokens(right)
    if not query_tokens or not document_tokens:
        return 0.0
    doc_counts: dict[str, int] = {}
    for token in document_tokens:
        doc_counts[token] = doc_counts.get(token, 0) + 1
    avgdl = max(1.0, (len(query_tokens) + len(document_tokens)) / 2)
    k1 = 1.2
    b = 0.75
    score = 0.0
    max_score = 0.0
    for token in query_tokens:
        idf = 1.0 + math.log(1.0 + (len(token) / 8.0))
        tf = doc_counts.get(token, 0)
        denom = tf + k1 * (1 - b + b * len(document_tokens) / avgdl)
        if tf:
            score += idf * ((tf * (k1 + 1)) / denom)
        max_score += idf * ((k1 + 1) / (1 + k1 * (1 - b + b * len(document_tokens) / avgdl)))
    return 0.0 if max_score <= 0 else max(0.0, min(1.0, score / max_score))


def _fixed_token_lexical_similarity(left: str, right: str) -> float:
    left_tokens = set(_fixed_tokens(left))
    right_tokens = set(_fixed_tokens(right))
    jaccard = (
        0.0
        if not left_tokens or not right_tokens
        else len(left_tokens & right_tokens) / len(left_tokens | right_tokens)
    )
    bm25 = max(_bm25_pair_similarity(left, right), _bm25_pair_similarity(right, left))
    return max(jaccard, bm25)


def _optional_text_similarity(left: str, right: str) -> float:
    if not left.strip() or not right.strip():
        return 0.0
    return _jaccard_similarity(left, right)


def _metadata_match_score(item: dict[str, Any], match: dict[str, Any]) -> float:
    metadata = _metadata_from_match(match)
    checks = [
        (
            str(item.get("service_name") or ""),
            str(metadata.get("service_name") or ""),
        ),
        (
            str(item.get("log_level") or "").upper(),
            str(metadata.get("log_level") or "").upper(),
        ),
    ]
    applicable = [(left, right) for left, right in checks if left and right]
    if not applicable:
        return 0.0
    return sum(1 for left, right in applicable if left == right) / len(applicable)


def _match_message(match: dict[str, Any]) -> str:
    metadata = _metadata_from_match(match)
    return str(
        metadata.get("normalized_message")
        or metadata.get("message")
        or match.get("document")
        or ""
    )


def _pattern_similarity(item: dict[str, Any], match: dict[str, Any]) -> float:
    embedding_similarity = max(0.0, min(1.0, float(match.get("similarity") or 0.0)))
    item_message = str(
        item.get("normalized_message") or item.get("message") or item.get("context") or ""
    )
    match_message = _match_message(match)
    item_stacktrace = str(item.get("stacktrace") or item.get("stack_trace") or "")
    match_stacktrace = str(_metadata_from_match(match).get("stacktrace") or "")
    weighted_scores = [
        (
            PATTERN_WEIGHTS["drain_template"],
            _drain_template_similarity(item_message, match_message),
        ),
        (
            PATTERN_WEIGHTS["fixed_token_lexical"],
            _fixed_token_lexical_similarity(item_message, match_message),
        ),
        (
            PATTERN_WEIGHTS["sequence_structure"],
            _template_structure_similarity(item_message, match_message),
        ),
        (PATTERN_WEIGHTS["metadata"], _metadata_match_score(item, match)),
        (PATTERN_WEIGHTS["embedding"], embedding_similarity),
    ]
    if _key_value_schema(item_message) or _key_value_schema(match_message):
        weighted_scores.append(
            (
                PATTERN_WEIGHTS["key_value_schema"],
                _key_value_schema_similarity(item_message, match_message),
            )
        )
    if item_stacktrace.strip() or match_stacktrace.strip():
        weighted_scores.append(
            (
                PATTERN_WEIGHTS["stacktrace"],
                _optional_text_similarity(item_stacktrace, match_stacktrace),
            )
        )
    total_weight = sum(weight for weight, _ in weighted_scores) or 1.0
    score = sum(weight * value for weight, value in weighted_scores) / total_weight
    return round(max(0.0, min(1.0, score)), 4)


def _hybrid_similarity(item: dict[str, Any], match: dict[str, Any]) -> float:
    return _pattern_similarity(item, match)


def _with_hybrid_similarity(
    item: dict[str, Any], matches: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for match in matches:
        pattern_similarity = _pattern_similarity(item, match)
        enriched.append(
            {
                **match,
                "pattern_similarity": pattern_similarity,
                "hybrid_similarity": pattern_similarity,
                "raw_similarity": match.get("similarity"),
            }
        )
    return enriched


def _match_with_group_context(
    match: dict[str, Any], target_group: dict[str, Any]
) -> dict[str, Any]:
    metadata = dict(_metadata_from_match(match))
    metadata.setdefault("fingerprint", target_group.get("fingerprint", ""))
    metadata.setdefault("service_name", target_group.get("service_name", ""))
    metadata.setdefault("log_level", target_group.get("log_level", ""))
    metadata.setdefault(
        "normalized_message",
        target_group.get("normalized_message")
        or normalize_log_text(str(target_group.get("message") or "")),
    )
    metadata.setdefault("message", target_group.get("message", ""))
    metadata.setdefault("stacktrace", target_group.get("stacktrace", ""))
    return {
        **match,
        "metadata": metadata,
        "document": match.get("document") or metadata.get("normalized_message") or "",
    }


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


def _connected_duplicate_components(
    edges: dict[str, set[str]], lookup: dict[str, dict[str, Any]]
) -> list[list[dict[str, Any]]]:
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


def _hdbscan_cluster_labels(
    distance_matrix: list[list[float]],
    *,
    min_cluster_size: int = HDBSCAN_MIN_CLUSTER_SIZE,
    min_samples: int = HDBSCAN_MIN_SAMPLES,
) -> list[int]:
    if len(distance_matrix) < min_cluster_size:
        return []
    try:
        numpy = importlib.import_module("numpy")
        hdbscan = importlib.import_module("hdbscan")
        clusterer = hdbscan.HDBSCAN(
            metric="precomputed",
            min_cluster_size=min_cluster_size,
            min_samples=min_samples,
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(numpy.array(distance_matrix))
    except Exception:  # noqa: BLE001
        return []
    return [int(label) for label in labels]


def _hdbscan_component_allowed(
    items: list[dict[str, Any]], pair_scores: dict[tuple[str, str], float]
) -> bool:
    fingerprints = [str(item.get("fingerprint") or "") for item in items]
    scores: list[float] = []
    for left_index, left in enumerate(fingerprints):
        for right in fingerprints[left_index + 1 :]:
            scores.append(pair_scores.get((left, right), pair_scores.get((right, left), 0.0)))
    if not scores:
        return False
    return (
        max(scores) >= PATTERN_DUPLICATE_SIMILARITY_THRESHOLD
        and sum(scores) / len(scores) >= 1.0 - (HDBSCAN_MAX_DISTANCE * 1.5)
    )


def _hdbscan_duplicate_groups(
    groups: list[dict[str, Any]],
    pair_scores: dict[tuple[str, str], float],
) -> list[list[dict[str, Any]]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for group in groups:
        service_name = str(group.get("service_name") or "")
        log_level = str(group.get("log_level") or "").upper()
        fingerprint = str(group.get("fingerprint") or "")
        if service_name and log_level and fingerprint:
            buckets.setdefault((service_name, log_level), []).append(group)

    clustered: list[list[dict[str, Any]]] = []
    for bucket_items in buckets.values():
        if len(bucket_items) < HDBSCAN_MIN_CLUSTER_SIZE:
            continue
        fingerprints = [str(item.get("fingerprint") or "") for item in bucket_items]
        matrix: list[list[float]] = []
        for left in fingerprints:
            row: list[float] = []
            for right in fingerprints:
                if left == right:
                    row.append(0.0)
                    continue
                score = pair_scores.get((left, right), pair_scores.get((right, left), 0.0))
                row.append(min(1.0, max(0.0, 1.0 - score)))
            matrix.append(row)

        labels = _hdbscan_cluster_labels(matrix)
        if not labels or len(labels) != len(bucket_items):
            continue
        by_label: dict[int, list[dict[str, Any]]] = {}
        for label, item in zip(labels, bucket_items, strict=False):
            if label < 0:
                continue
            by_label.setdefault(label, []).append(item)
        clustered.extend(
            items
            for items in by_label.values()
            if len(items) >= 2 and _hdbscan_component_allowed(items, pair_scores)
        )
    return clustered


def _cosine_distance_matrix(embeddings: list[list[float]]) -> list[list[float]]:
    try:
        numpy = importlib.import_module("numpy")
        pairwise = importlib.import_module("sklearn.metrics.pairwise")
        distances = pairwise.cosine_distances(numpy.array(embeddings, dtype=float))
    except Exception:  # noqa: BLE001
        return []
    return [[float(value) for value in row] for row in distances.tolist()]


def _semantic_cluster_labels_from_embeddings(
    embeddings: list[list[float]],
) -> tuple[list[int], str]:
    labels = _hdbscan_cluster_labels(
        _cosine_distance_matrix(embeddings),
        min_cluster_size=SEMANTIC_CLUSTER_MIN_CLUSTER_SIZE,
        min_samples=SEMANTIC_CLUSTER_MIN_SAMPLES,
    )
    if labels and len(labels) == len(embeddings):
        return labels, "openai_l2_hdbscan"
    return [], "drain3_template_fallback"


def _representative_cluster_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        items,
        key=lambda item: (
            int(item.get("occurrence_count") or 0),
            str(item.get("log_level") or "") in {"ERROR", "CRITICAL"},
            str(item.get("last_seen") or ""),
        ),
    )


def _semantic_log_cluster_id(
    *,
    service_name: str,
    algorithm: str,
    fingerprints: list[str],
) -> str:
    members = "|".join(sorted(fingerprint for fingerprint in fingerprints if fingerprint))
    raw = f"{service_name}|{algorithm}|{members}"
    return "SC-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def _build_semantic_cluster_record(
    *,
    index: int,
    items: list[dict[str, Any]],
    algorithm: str,
    recommendations_by_fp: dict[str, dict[str, Any]],
    impacts_by_fp: dict[str, dict[str, Any]],
    anomalies_by_fp: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    representative = _representative_cluster_item(items)
    representative_fp = str(representative.get("fingerprint") or "")
    representative_recommendation = recommendations_by_fp.get(representative_fp, {})
    risk_scores = [
        int(impacts_by_fp.get(str(item.get("fingerprint") or ""), {}).get("risk_score") or 0)
        for item in items
    ]
    fingerprints = [str(item.get("fingerprint") or "") for item in items]
    service_name = str(representative.get("service_name") or "")
    return {
        "cluster_id": _semantic_log_cluster_id(
            service_name=service_name,
            algorithm=algorithm,
            fingerprints=fingerprints,
        ),
        "rank": index,
        "algorithm": algorithm,
        "count": sum(int(item.get("occurrence_count") or 0) for item in items),
        "fingerprint_count": len(items),
        "fingerprints": fingerprints,
        "service_name": service_name,
        "log_level": str(representative.get("log_level") or ""),
        "drain_template": str(
            representative.get("drain_template")
            or drain_log_template(str(representative.get("message") or ""))
        ),
        "representative_fingerprint": representative_fp,
        "representative_log": str(representative.get("message") or ""),
        "representative_cause": str(representative_recommendation.get("cause") or ""),
        "recommendation_hint": str(
            representative_recommendation.get("recommendation") or ""
        ),
        "risk_score": max(risk_scores, default=0),
        "anomaly_count": sum(1 for fp in fingerprints if fp in anomalies_by_fp),
        "pattern_statuses": sorted(
            {
                str(item.get("pattern_status") or "")
                for item in items
                if str(item.get("pattern_status") or "")
            }
        ),
    }


def _fallback_semantic_cluster_groups(
    groups: list[dict[str, Any]],
) -> list[list[dict[str, Any]]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for group in groups:
        key = (
            str(group.get("service_name") or ""),
            str(group.get("log_level") or ""),
            str(group.get("drain_template") or drain_log_template(str(group.get("message") or ""))),
        )
        buckets.setdefault(key, []).append(group)
    return sorted(
        buckets.values(),
        key=lambda items: (
            -sum(int(item.get("occurrence_count") or 0) for item in items),
            str(_representative_cluster_item(items).get("fingerprint") or ""),
        ),
    )


def build_semantic_log_clusters(
    groups: list[dict[str, Any]],
    *,
    recommendations: list[dict[str, Any]] | None = None,
    impacts: list[dict[str, Any]] | None = None,
    anomalies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Cluster Drain templates with OpenAI embeddings and HDBSCAN."""

    if not groups:
        return []
    enriched_groups = _apply_drain_templates(groups)
    recommendations_by_fp = {
        str(item.get("fingerprint") or ""): item for item in recommendations or []
    }
    impacts_by_fp = {str(item.get("fingerprint") or ""): item for item in impacts or []}
    anomalies_by_fp = {
        str(item.get("pattern") or ""): item for item in anomalies or [] if item.get("pattern")
    }

    enriched_groups = _attach_detection_features(
        enriched_groups,
        impacts=impacts,
        anomalies=anomalies,
    )

    cluster_groups: list[list[dict[str, Any]]] = []
    algorithm = "drain3_template_fallback"
    hybrid_vectors = _hybrid_vectors_for_groups(enriched_groups)
    if hybrid_vectors and len(hybrid_vectors) == len(enriched_groups):
        labels, algorithm = _semantic_cluster_labels_from_embeddings(hybrid_vectors)
        algorithm = algorithm.replace("openai_l2", HYBRID_VECTOR_SCHEMA_VERSION)
        if labels:
            by_label: dict[int, list[dict[str, Any]]] = {}
            noise_items: list[dict[str, Any]] = []
            for label, item in zip(labels, enriched_groups, strict=False):
                if label < 0:
                    noise_items.append(item)
                else:
                    by_label.setdefault(label, []).append(item)
            cluster_groups = [
                items
                for items in by_label.values()
                if len(items) >= SEMANTIC_CLUSTER_MIN_SAMPLES
            ]
            if noise_items:
                cluster_groups.extend(_fallback_semantic_cluster_groups(noise_items))
    if not cluster_groups:
        cluster_groups = _fallback_semantic_cluster_groups(enriched_groups)
        algorithm = "drain3_template_fallback"

    cluster_groups = sorted(
        cluster_groups,
        key=lambda items: (
            -sum(int(item.get("occurrence_count") or 0) for item in items),
            str(_representative_cluster_item(items).get("fingerprint") or ""),
        ),
    )
    return [
        _build_semantic_cluster_record(
            index=index,
            items=items,
            algorithm=algorithm,
            recommendations_by_fp=recommendations_by_fp,
            impacts_by_fp=impacts_by_fp,
            anomalies_by_fp=anomalies_by_fp,
        )
        for index, items in enumerate(cluster_groups, start=1)
    ]


def _upsert_semantic_log_clusters(
    conn: sqlite3.Connection,
    *,
    clusters: list[dict[str, Any]],
    analysis_date: str,
    service_name: str | None,
) -> None:
    if service_name:
        conn.execute(
            "DELETE FROM semantic_log_clusters WHERE service_name=? AND analysis_date=?",
            (service_name, analysis_date),
        )
    else:
        conn.execute(
            "DELETE FROM semantic_log_clusters WHERE analysis_date=?",
            (analysis_date,),
        )
    if not clusters:
        return
    conn.executemany(
        """
        INSERT INTO semantic_log_clusters(
            cluster_id, analysis_date, service_name, log_level, algorithm,
            representative_fingerprint, representative_log, representative_cause,
            recommendation_hint, drain_template, fingerprints_json,
            pattern_statuses_json, count, fingerprint_count, risk_score,
            anomaly_count, evidence_schema_version, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'semantic-log-cluster-v1', CURRENT_TIMESTAMP)
        ON CONFLICT(cluster_id) DO UPDATE SET
            analysis_date=excluded.analysis_date,
            service_name=excluded.service_name,
            log_level=excluded.log_level,
            algorithm=excluded.algorithm,
            representative_fingerprint=excluded.representative_fingerprint,
            representative_log=excluded.representative_log,
            representative_cause=excluded.representative_cause,
            recommendation_hint=excluded.recommendation_hint,
            drain_template=excluded.drain_template,
            fingerprints_json=excluded.fingerprints_json,
            pattern_statuses_json=excluded.pattern_statuses_json,
            count=excluded.count,
            fingerprint_count=excluded.fingerprint_count,
            risk_score=excluded.risk_score,
            anomaly_count=excluded.anomaly_count,
            evidence_schema_version=excluded.evidence_schema_version,
            updated_at=CURRENT_TIMESTAMP
        """,
        [
            (
                str(cluster.get("cluster_id") or ""),
                analysis_date,
                str(cluster.get("service_name") or service_name or ""),
                str(cluster.get("log_level") or ""),
                str(cluster.get("algorithm") or ""),
                str(cluster.get("representative_fingerprint") or ""),
                str(cluster.get("representative_log") or ""),
                str(cluster.get("representative_cause") or ""),
                str(cluster.get("recommendation_hint") or ""),
                str(cluster.get("drain_template") or ""),
                _json_list(cluster.get("fingerprints") or []),
                _json_list(cluster.get("pattern_statuses") or []),
                int(cluster.get("count") or 0),
                int(cluster.get("fingerprint_count") or 0),
                int(cluster.get("risk_score") or 0),
                int(cluster.get("anomaly_count") or 0),
            )
            for cluster in clusters
            if str(cluster.get("cluster_id") or "")
        ],
    )


def _fetch_semantic_log_clusters(
    conn: sqlite3.Connection,
    *,
    service_name: str | None = None,
    analysis_date: str | None = None,
    fingerprints: set[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    clauses: list[str] = []
    if service_name:
        clauses.append("service_name=?")
        params.append(service_name)
    if analysis_date:
        clauses.append("analysis_date=?")
        params.append(analysis_date)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT cluster_id, analysis_date, service_name, log_level, algorithm,
               representative_fingerprint, representative_log, representative_cause,
               recommendation_hint, drain_template, fingerprints_json,
               pattern_statuses_json, count, fingerprint_count, risk_score,
               anomaly_count, evidence_schema_version
        FROM semantic_log_clusters
        {where}
        ORDER BY risk_score DESC, count DESC, fingerprint_count DESC, cluster_id ASC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    clusters: list[dict[str, Any]] = []
    for row in rows:
        cluster_fingerprints = [
            str(item) for item in _load_json_list(str(row[10] or "[]"))
        ]
        if fingerprints and not (set(cluster_fingerprints) & fingerprints):
            continue
        clusters.append(
            {
                "cluster_id": str(row[0]),
                "analysis_date": str(row[1] or ""),
                "service_name": str(row[2] or ""),
                "log_level": str(row[3] or ""),
                "algorithm": str(row[4] or ""),
                "representative_fingerprint": str(row[5] or ""),
                "representative_log": str(row[6] or ""),
                "representative_cause": str(row[7] or ""),
                "recommendation_hint": str(row[8] or ""),
                "drain_template": str(row[9] or ""),
                "fingerprints": cluster_fingerprints,
                "pattern_statuses": [
                    str(item) for item in _load_json_list(str(row[11] or "[]"))
                ],
                "count": int(row[12] or 0),
                "fingerprint_count": int(row[13] or 0),
                "risk_score": int(row[14] or 0),
                "anomaly_count": int(row[15] or 0),
                "evidence_schema_version": str(row[16] or ""),
            }
        )
    return clusters


def fetch_semantic_log_clusters(
    *,
    service_name: str | None = None,
    analysis_date: str | None = None,
    fingerprints: set[str] | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    db_path = _resolve_db_path()
    if not Path(db_path).exists():
        return []
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        return _fetch_semantic_log_clusters(
            conn,
            service_name=service_name,
            analysis_date=analysis_date,
            fingerprints=fingerprints,
            limit=limit,
        )


def _pattern_cluster_text(item: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"service={item.get('service_name', '')}",
            f"level={item.get('log_level', '')}",
            f"fingerprint={item.get('fingerprint', '')}",
            f"drain_template={item.get('drain_template') or drain_log_template(str(item.get('message') or ''))}",
            f"normalized_message={item.get('normalized_message') or normalize_log_text(str(item.get('message') or ''))}",
            f"stacktrace={item.get('stacktrace', '')}",
        ]
    )


def _cosine_score(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0
    return round(
        max(
            0.0,
            min(
                1.0,
                sum(
                    float(left_value) * float(right_value)
                    for left_value, right_value in zip(left, right, strict=False)
                ),
            ),
        ),
        4,
    )


def _l2_normalized(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if norm <= 0:
        return [0.0 for _ in values]
    return [round(float(value) / norm, 8) for value in values]


def _pattern_template_embedding_text(item: dict[str, Any]) -> str:
    template = str(
        item.get("drain_template")
        or item.get("message_template")
        or item.get("normalized_message")
        or ""
    ).strip()
    if template:
        return template
    return drain_log_template(str(item.get("message") or ""))


def _hash_category_features(item: dict[str, Any]) -> list[float]:
    vector = [0.0 for _ in range(HYBRID_HASH_DIMENSIONS)]
    categories = [
        ("service", str(item.get("service_name") or "")),
        ("level", str(item.get("log_level") or "").upper()),
        ("fingerprint", str(item.get("fingerprint") or "")),
    ]
    for namespace, value in categories:
        if not value:
            continue
        digest = hashlib.sha256(f"{namespace}:{value}".encode()).digest()
        index = int.from_bytes(digest[:2], "big") % HYBRID_HASH_DIMENSIONS
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign
    return _l2_normalized(vector)


def _level_score(level: str) -> float:
    return {
        "TRACE": 0.05,
        "DEBUG": 0.10,
        "INFO": 0.20,
        "WARN": 0.55,
        "WARNING": 0.55,
        "ERROR": 0.85,
        "CRITICAL": 1.0,
        "FATAL": 1.0,
    }.get(level.upper(), 0.0)


def _hybrid_numeric_features(item: dict[str, Any]) -> list[float]:
    occurrence_count = max(0.0, float(item.get("occurrence_count") or 0))
    risk_score = max(0.0, min(100.0, float(item.get("risk_score") or 0)))
    anomaly_count = max(
        0.0,
        float(
            item.get("anomaly_count")
            or item.get("anomaly_detected")
            or item.get("anomalies")
            or 0
        ),
    )
    status = str(item.get("pattern_status") or "")
    return [
        min(1.0, math.log1p(occurrence_count) / math.log1p(1000.0)),
        risk_score / 100.0,
        min(1.0, math.log1p(anomaly_count) / math.log1p(10.0)),
        _level_score(str(item.get("log_level") or "")),
        1.0 if status in {"known_exact", "known_similar"} else 0.0,
        1.0 if status == "new_pattern" else 0.0,
    ]


def _hybrid_vector(
    item: dict[str, Any], text_embedding: list[float] | None
) -> list[float]:
    categorical = _hash_category_features(item)
    numeric = _hybrid_numeric_features(item)
    if text_embedding:
        vector = [
            *(float(value) * HYBRID_TEXT_WEIGHT for value in text_embedding),
            *(value * HYBRID_CATEGORICAL_WEIGHT for value in categorical),
            *(value * HYBRID_NUMERIC_WEIGHT for value in numeric),
        ]
    else:
        vector = [
            *(value * HYBRID_NO_TEXT_CATEGORICAL_WEIGHT for value in categorical),
            *(value * HYBRID_NO_TEXT_NUMERIC_WEIGHT for value in numeric),
        ]
    return _l2_normalized(vector)


def _hybrid_vectors_for_groups(groups: list[dict[str, Any]]) -> list[list[float]]:
    texts = [_pattern_template_embedding_text(item) for item in groups]
    embeddings = embed_pattern_texts_normalized(texts)
    text_embeddings: list[list[float] | None]
    if embeddings is not None and len(embeddings) == len(groups):
        text_embeddings = embeddings
    else:
        text_embeddings = [None for _ in groups]
    return [
        _hybrid_vector(item, text_embeddings[index])
        for index, item in enumerate(groups)
    ]


def _mean_vector(vectors: list[list[float]]) -> list[float]:
    non_empty = [vector for vector in vectors if vector]
    if not non_empty:
        return []
    width = max(len(vector) for vector in non_empty)
    totals = [0.0 for _ in range(width)]
    for vector in non_empty:
        for index, value in enumerate(vector):
            totals[index] += float(value)
    return _l2_normalized([value / len(non_empty) for value in totals])


def _attach_detection_features(
    groups: list[dict[str, Any]],
    *,
    impacts: list[dict[str, Any]] | None = None,
    anomalies: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    impacts_by_fp = {str(item.get("fingerprint") or ""): item for item in impacts or []}
    anomaly_counts: dict[str, int] = {}
    for item in anomalies or []:
        fingerprint = str(item.get("pattern") or item.get("fingerprint") or "")
        if fingerprint:
            anomaly_counts[fingerprint] = anomaly_counts.get(fingerprint, 0) + 1
    enriched: list[dict[str, Any]] = []
    for group in groups:
        fingerprint = str(group.get("fingerprint") or "")
        impact = impacts_by_fp.get(fingerprint, {})
        enriched.append(
            {
                **group,
                "risk_score": int(impact.get("risk_score") or group.get("risk_score") or 0),
                "anomaly_count": anomaly_counts.get(
                    fingerprint, int(group.get("anomaly_count") or 0)
                ),
            }
        )
    return enriched


def _pattern_cluster_match_from_group(
    target: dict[str, Any], *, semantic_similarity: float
) -> dict[str, Any]:
    metadata = {
        "fingerprint": str(target.get("fingerprint") or ""),
        "service_name": str(target.get("service_name") or ""),
        "log_level": str(target.get("log_level") or ""),
        "normalized_message": str(
            target.get("normalized_message")
            or normalize_log_text(str(target.get("message") or ""))
        ),
        "message": str(target.get("message") or ""),
        "stacktrace": str(target.get("stacktrace") or ""),
    }
    return {
        "id": f"{metadata['service_name']}:{metadata['fingerprint']}",
        "document": _pattern_cluster_text(target),
        "metadata": metadata,
        "similarity": semantic_similarity,
    }


def _hybrid_cluster_score(pattern_similarity: float, semantic_similarity: float) -> float:
    return round(
        (pattern_similarity * PATTERN_CLUSTER_HYBRID_PATTERN_WEIGHT)
        + (semantic_similarity * PATTERN_CLUSTER_HYBRID_SEMANTIC_WEIGHT),
        4,
    )


def _pattern_cluster_match_type(
    *, pattern_similarity: float, semantic_similarity: float, exact: bool = False
) -> str:
    if exact:
        return "exact"
    if pattern_similarity >= PATTERN_CLUSTER_MEMBER_THRESHOLD:
        return "pattern_match"
    if (
        pattern_similarity >= PATTERN_CLUSTER_HYBRID_PATTERN_THRESHOLD
        and semantic_similarity >= PATTERN_CLUSTER_SEMANTIC_LINK_THRESHOLD
    ):
        return "hybrid_match"
    if semantic_similarity >= PATTERN_CLUSTER_SEMANTIC_LINK_THRESHOLD:
        return "semantic_match"
    return "weak"


def _pattern_cluster_member_pair(
    *, pattern_similarity: float, semantic_similarity: float
) -> bool:
    return _pattern_cluster_match_type(
        pattern_similarity=pattern_similarity,
        semantic_similarity=semantic_similarity,
    ) in {"pattern_match", "hybrid_match"}


def _pattern_cluster_pair_scores(
    groups: list[dict[str, Any]],
) -> tuple[
    list[dict[str, Any]],
    dict[tuple[str, str], dict[str, float]],
    dict[str, list[float]],
]:
    enriched = _apply_drain_templates(groups)
    vectors = _hybrid_vectors_for_groups(enriched)
    vectors_by_fp = {
        str(item.get("fingerprint") or ""): vectors[index]
        for index, item in enumerate(enriched)
        if str(item.get("fingerprint") or "")
    }
    signatures = [
        duplicate_candidate_signature(str(item.get("message") or ""))
        for item in enriched
    ]
    scores: dict[tuple[str, str], dict[str, float]] = {}
    for left_index, left in enumerate(enriched):
        left_fp = str(left.get("fingerprint") or "")
        left_template = str(left.get("drain_template") or "")
        for right_index in range(left_index + 1, len(enriched)):
            right = enriched[right_index]
            right_fp = str(right.get("fingerprint") or "")
            if not left_fp or not right_fp:
                continue
            if str(left.get("service_name") or "") != str(right.get("service_name") or ""):
                continue
            if str(left.get("log_level") or "").upper() != str(
                right.get("log_level") or ""
            ).upper():
                continue
            semantic_similarity = _cosine_score(vectors[left_index], vectors[right_index])
            right_template = str(right.get("drain_template") or "")
            same_template = bool(left_template and left_template == right_template)
            same_signature = bool(
                signatures[left_index]
                and signatures[left_index] == signatures[right_index]
            )
            if (
                not same_template
                and not same_signature
                and semantic_similarity < PATTERN_CLUSTER_SEMANTIC_LINK_THRESHOLD
            ):
                continue
            left_match = _pattern_cluster_match_from_group(
                right, semantic_similarity=semantic_similarity
            )
            right_match = _pattern_cluster_match_from_group(
                left, semantic_similarity=semantic_similarity
            )
            pattern_similarity = max(
                _pattern_similarity(left, left_match),
                _pattern_similarity(right, right_match),
            )
            hybrid_score = _hybrid_cluster_score(
                pattern_similarity, semantic_similarity
            )
            scores[(left_fp, right_fp)] = {
                "pattern_similarity": pattern_similarity,
                "semantic_similarity": semantic_similarity,
                "hybrid_score": hybrid_score,
            }
    return enriched, scores, vectors_by_fp


def _pattern_cluster_score_for_pair(
    pair_scores: dict[tuple[str, str], dict[str, float]], left: str, right: str
) -> dict[str, float]:
    if left == right:
        return {
            "pattern_similarity": 1.0,
            "semantic_similarity": 1.0,
            "hybrid_score": 1.0,
        }
    return pair_scores.get((left, right), pair_scores.get((right, left), {}))


def _connected_pattern_components(
    groups: list[dict[str, Any]], pair_scores: dict[tuple[str, str], dict[str, float]]
) -> list[set[str]]:
    lookup = {str(group.get("fingerprint") or ""): group for group in groups}
    edges: dict[str, set[str]] = {fingerprint: set() for fingerprint in lookup}
    for (left, right), score in pair_scores.items():
        if _pattern_cluster_member_pair(
            pattern_similarity=float(score.get("pattern_similarity") or 0),
            semantic_similarity=float(score.get("semantic_similarity") or 0),
        ):
            edges[left].add(right)
            edges[right].add(left)
    seen: set[str] = set()
    components: list[set[str]] = []
    for fingerprint in edges:
        if fingerprint in seen:
            continue
        stack = [fingerprint]
        component: set[str] = set()
        seen.add(fingerprint)
        while stack:
            current = stack.pop()
            component.add(current)
            for next_fingerprint in edges[current]:
                if next_fingerprint not in seen:
                    seen.add(next_fingerprint)
                    stack.append(next_fingerprint)
        components.append(component)
    return components


def _hdbscan_pattern_components(
    groups: list[dict[str, Any]], pair_scores: dict[tuple[str, str], dict[str, float]]
) -> list[set[str]]:
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for group in groups:
        service_name = str(group.get("service_name") or "")
        log_level = str(group.get("log_level") or "").upper()
        fingerprint = str(group.get("fingerprint") or "")
        if service_name and log_level and fingerprint:
            buckets.setdefault((service_name, log_level), []).append(group)

    components: list[set[str]] = []
    for bucket_items in buckets.values():
        if len(bucket_items) < HDBSCAN_MIN_CLUSTER_SIZE:
            continue
        fingerprints = [str(item.get("fingerprint") or "") for item in bucket_items]
        matrix: list[list[float]] = []
        for left in fingerprints:
            row: list[float] = []
            for right in fingerprints:
                if left == right:
                    row.append(0.0)
                    continue
                score = _pattern_cluster_score_for_pair(pair_scores, left, right)
                row.append(
                    min(
                        1.0,
                        max(0.0, 1.0 - float(score.get("pattern_similarity") or 0.0)),
                    )
                )
            matrix.append(row)
        labels = _hdbscan_cluster_labels(matrix)
        if not labels or len(labels) != len(bucket_items):
            continue
        by_label: dict[int, set[str]] = {}
        for label, fingerprint in zip(labels, fingerprints, strict=False):
            if label < 0:
                continue
            by_label.setdefault(label, set()).add(fingerprint)
        for component in by_label.values():
            if len(component) >= 2:
                components.append(component)
    return components


def _merge_pattern_components(components: list[set[str]], all_fingerprints: set[str]) -> list[set[str]]:
    merged: list[set[str]] = []
    for component in components:
        if not component:
            continue
        overlaps = [index for index, item in enumerate(merged) if item & component]
        if not overlaps:
            merged.append(set(component))
            continue
        target_index = overlaps[0]
        merged[target_index].update(component)
        for index in reversed(overlaps[1:]):
            merged[target_index].update(merged[index])
            del merged[index]
    assigned = set().union(*merged) if merged else set()
    for fingerprint in sorted(all_fingerprints - assigned):
        merged.append({fingerprint})
    return sorted(merged, key=lambda item: (len(item), sorted(item)[0]), reverse=True)


def _canonical_pattern_item(items: list[dict[str, Any]]) -> dict[str, Any]:
    def priority(item: dict[str, Any]) -> tuple[int, int, str]:
        status = str(item.get("pattern_status") or "")
        known_score = 2 if status == "known_exact" else 1 if status == "known_similar" else 0
        return (
            known_score,
            int(item.get("occurrence_count") or 0),
            str(item.get("last_seen") or ""),
        )

    return max(items, key=priority)


def _pattern_cluster_id(service_name: str, log_level: str, canonical_fingerprint: str) -> str:
    raw = f"{service_name}|{log_level.upper()}|{canonical_fingerprint}"
    return "PC-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10].upper()


def _pattern_cluster_algorithm(
    component: set[str], hdbscan_components: list[set[str]]
) -> str:
    if any(component <= hdbscan_component for hdbscan_component in hdbscan_components):
        return "connected_component+hdbscan"
    return "connected_component"


def _delete_pattern_clusters_for_services(
    conn: sqlite3.Connection, service_names: set[str]
) -> None:
    if not service_names:
        return
    placeholders = ",".join("?" for _ in service_names)
    cluster_ids = [
        str(row[0])
        for row in conn.execute(
            f"SELECT cluster_id FROM pattern_clusters WHERE service_name IN ({placeholders})",
            sorted(service_names),
        ).fetchall()
    ]
    if cluster_ids:
        cluster_placeholders = ",".join("?" for _ in cluster_ids)
        conn.execute(
            f"DELETE FROM pattern_cluster_members WHERE cluster_id IN ({cluster_placeholders})",
            cluster_ids,
        )
        conn.execute(
            f"""
            DELETE FROM pattern_cluster_links
            WHERE source_cluster_id IN ({cluster_placeholders})
               OR target_cluster_id IN ({cluster_placeholders})
            """,
            [*cluster_ids, *cluster_ids],
        )
    conn.execute(
        f"DELETE FROM pattern_clusters WHERE service_name IN ({placeholders})",
        sorted(service_names),
    )


def _upsert_pattern_cluster_records(
    conn: sqlite3.Connection,
    *,
    groups: list[dict[str, Any]],
    pair_scores: dict[tuple[str, str], dict[str, float]],
    hybrid_vectors_by_fp: dict[str, list[float]],
    components: list[set[str]],
    hdbscan_components: list[set[str]],
) -> list[dict[str, Any]]:
    lookup = {str(group.get("fingerprint") or ""): group for group in groups}
    service_names = {str(group.get("service_name") or "") for group in groups if group.get("service_name")}
    _delete_pattern_clusters_for_services(conn, service_names)

    cluster_records: list[dict[str, Any]] = []
    cluster_by_fingerprint: dict[str, str] = {}
    for component in components:
        items = [lookup[fingerprint] for fingerprint in sorted(component) if fingerprint in lookup]
        if not items:
            continue
        canonical = _canonical_pattern_item(items)
        canonical_fp = str(canonical.get("fingerprint") or "")
        service_name = str(canonical.get("service_name") or "")
        log_level = str(canonical.get("log_level") or "").upper()
        cluster_id = _pattern_cluster_id(service_name, log_level, canonical_fp)
        member_scores = [
            _pattern_cluster_score_for_pair(
                pair_scores, canonical_fp, str(item.get("fingerprint") or "")
            )
            for item in items
        ]
        pattern_values = [float(score.get("pattern_similarity") or 0) for score in member_scores]
        semantic_values = [
            float(score.get("semantic_similarity") or 0) for score in member_scores
        ]
        total_count = sum(int(item.get("occurrence_count") or 0) for item in items)
        known_status = str(canonical.get("pattern_status") or "")
        algorithm = _pattern_cluster_algorithm(component, hdbscan_components)
        hybrid_vector = _mean_vector(
            [
                hybrid_vectors_by_fp.get(str(item.get("fingerprint") or ""), [])
                for item in items
            ]
        )
        representative_template = str(
            canonical.get("drain_template")
            or drain_log_template(str(canonical.get("message") or ""))
        )
        conn.execute(
            """
            INSERT INTO pattern_clusters(
                cluster_id, service_name, log_level, canonical_fingerprint,
                representative_template, representative_message, algorithm,
                member_count, total_occurrence_count, avg_pattern_similarity,
                min_pattern_similarity, avg_semantic_similarity,
                max_semantic_similarity, known_status, hybrid_vector_json,
                hybrid_vector_schema_version, status, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', CURRENT_TIMESTAMP)
            ON CONFLICT(cluster_id) DO UPDATE SET
                service_name=excluded.service_name,
                log_level=excluded.log_level,
                canonical_fingerprint=excluded.canonical_fingerprint,
                representative_template=excluded.representative_template,
                representative_message=excluded.representative_message,
                algorithm=excluded.algorithm,
                member_count=excluded.member_count,
                total_occurrence_count=excluded.total_occurrence_count,
                avg_pattern_similarity=excluded.avg_pattern_similarity,
                min_pattern_similarity=excluded.min_pattern_similarity,
                avg_semantic_similarity=excluded.avg_semantic_similarity,
                max_semantic_similarity=excluded.max_semantic_similarity,
                known_status=excluded.known_status,
                hybrid_vector_json=excluded.hybrid_vector_json,
                hybrid_vector_schema_version=excluded.hybrid_vector_schema_version,
                status=excluded.status,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                cluster_id,
                service_name,
                log_level,
                canonical_fp,
                representative_template,
                str(canonical.get("message") or ""),
                algorithm,
                len(items),
                total_count,
                round(sum(pattern_values) / len(pattern_values), 4) if pattern_values else 0,
                round(min(pattern_values), 4) if pattern_values else 0,
                round(sum(semantic_values) / len(semantic_values), 4) if semantic_values else 0,
                round(max(semantic_values), 4) if semantic_values else 0,
                known_status,
                _json_list(hybrid_vector),
                HYBRID_VECTOR_SCHEMA_VERSION,
            ),
        )
        members: list[dict[str, Any]] = []
        for item, score in zip(items, member_scores, strict=False):
            fingerprint = str(item.get("fingerprint") or "")
            exact = fingerprint == canonical_fp
            pattern_similarity = float(score.get("pattern_similarity") or 0)
            semantic_similarity = float(score.get("semantic_similarity") or 0)
            match_type = _pattern_cluster_match_type(
                pattern_similarity=pattern_similarity,
                semantic_similarity=semantic_similarity,
                exact=exact,
            )
            role = "canonical" if exact else "member"
            hybrid_score = _hybrid_cluster_score(pattern_similarity, semantic_similarity)
            conn.execute(
                """
                INSERT INTO pattern_cluster_members(
                    cluster_id, fingerprint, role, pattern_similarity,
                    semantic_similarity, hybrid_score, match_type,
                    occurrence_count, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(cluster_id, fingerprint) DO UPDATE SET
                    role=excluded.role,
                    pattern_similarity=excluded.pattern_similarity,
                    semantic_similarity=excluded.semantic_similarity,
                    hybrid_score=excluded.hybrid_score,
                    match_type=excluded.match_type,
                    occurrence_count=excluded.occurrence_count,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    cluster_id,
                    fingerprint,
                    role,
                    pattern_similarity,
                    semantic_similarity,
                    hybrid_score,
                    match_type,
                    int(item.get("occurrence_count") or 0),
                ),
            )
            cluster_by_fingerprint[fingerprint] = cluster_id
            members.append(
                {
                    "fingerprint": fingerprint,
                    "role": role,
                    "pattern_similarity": pattern_similarity,
                    "semantic_similarity": semantic_similarity,
                    "hybrid_score": hybrid_score,
                    "match_type": match_type,
                    "occurrence_count": int(item.get("occurrence_count") or 0),
                }
            )
        cluster_records.append(
            {
                "cluster_id": cluster_id,
                "service_name": service_name,
                "log_level": log_level,
                "canonical_fingerprint": canonical_fp,
                "representative_template": representative_template,
                "representative_message": str(canonical.get("message") or ""),
                "algorithm": algorithm,
                "member_count": len(items),
                "total_occurrence_count": total_count,
                "avg_pattern_similarity": round(sum(pattern_values) / len(pattern_values), 4)
                if pattern_values
                else 0,
                "min_pattern_similarity": round(min(pattern_values), 4)
                if pattern_values
                else 0,
                "avg_semantic_similarity": round(sum(semantic_values) / len(semantic_values), 4)
                if semantic_values
                else 0,
                "max_semantic_similarity": round(max(semantic_values), 4)
                if semantic_values
                else 0,
                "known_status": known_status,
                "hybrid_vector": hybrid_vector,
                "hybrid_vector_schema_version": HYBRID_VECTOR_SCHEMA_VERSION,
                "members": members,
                "links": [],
            }
        )

    best_links: dict[tuple[str, str], dict[str, Any]] = {}
    for (left, right), score in pair_scores.items():
        left_cluster = cluster_by_fingerprint.get(left)
        right_cluster = cluster_by_fingerprint.get(right)
        if not left_cluster or not right_cluster or left_cluster == right_cluster:
            continue
        semantic_similarity = float(score.get("semantic_similarity") or 0)
        if semantic_similarity < PATTERN_CLUSTER_SEMANTIC_LINK_THRESHOLD:
            continue
        source, target = sorted([left_cluster, right_cluster])
        key = (source, target)
        candidate = {
            "source_cluster_id": source,
            "target_cluster_id": target,
            "pattern_similarity": float(score.get("pattern_similarity") or 0),
            "semantic_similarity": semantic_similarity,
            "hybrid_score": float(score.get("hybrid_score") or 0),
            "link_type": _pattern_cluster_match_type(
                pattern_similarity=float(score.get("pattern_similarity") or 0),
                semantic_similarity=semantic_similarity,
            ),
        }
        current = best_links.get(key)
        if current is None or candidate["semantic_similarity"] > current["semantic_similarity"]:
            best_links[key] = candidate

    link_counts: dict[str, int] = {}
    for link in sorted(
        best_links.values(),
        key=lambda item: (
            float(item["semantic_similarity"]),
            float(item["pattern_similarity"]),
        ),
        reverse=True,
    ):
        source = str(link["source_cluster_id"])
        target = str(link["target_cluster_id"])
        if (
            link_counts.get(source, 0) >= PATTERN_CLUSTER_MAX_LINKS_PER_CLUSTER
            or link_counts.get(target, 0) >= PATTERN_CLUSTER_MAX_LINKS_PER_CLUSTER
        ):
            continue
        conn.execute(
            """
            INSERT INTO pattern_cluster_links(
                source_cluster_id, target_cluster_id, pattern_similarity,
                semantic_similarity, hybrid_score, link_type, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(source_cluster_id, target_cluster_id) DO UPDATE SET
                pattern_similarity=excluded.pattern_similarity,
                semantic_similarity=excluded.semantic_similarity,
                hybrid_score=excluded.hybrid_score,
                link_type=excluded.link_type,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                source,
                target,
                link["pattern_similarity"],
                link["semantic_similarity"],
                link["hybrid_score"],
                link["link_type"],
            ),
        )
        link_counts[source] = link_counts.get(source, 0) + 1
        link_counts[target] = link_counts.get(target, 0) + 1
        for cluster in cluster_records:
            if cluster["cluster_id"] in {source, target}:
                cluster["links"].append(link)
    return sorted(
        cluster_records,
        key=lambda item: (
            -int(item["total_occurrence_count"]),
            str(item["cluster_id"]),
        ),
    )


def build_pattern_clusters(
    conn: sqlite3.Connection, groups: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Persist canonical pattern clusters using pattern and semantic similarity."""

    if not groups:
        return []
    enriched_groups, pair_scores, hybrid_vectors_by_fp = _pattern_cluster_pair_scores(groups)
    all_fingerprints = {
        str(group.get("fingerprint") or "")
        for group in enriched_groups
        if group.get("fingerprint")
    }
    connected_components = _connected_pattern_components(enriched_groups, pair_scores)
    hdbscan_components = _hdbscan_pattern_components(enriched_groups, pair_scores)
    components = _merge_pattern_components(
        [*connected_components, *hdbscan_components],
        all_fingerprints,
    )
    return _upsert_pattern_cluster_records(
        conn,
        groups=enriched_groups,
        pair_scores=pair_scores,
        hybrid_vectors_by_fp=hybrid_vectors_by_fp,
        components=components,
        hdbscan_components=hdbscan_components,
    )


def fetch_pattern_clusters(
    *, service_name: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    db_path = _resolve_db_path()
    if not Path(db_path).exists():
        return []
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        return _fetch_pattern_clusters(conn, service_name=service_name, limit=limit)


def _fetch_pattern_clusters(
    conn: sqlite3.Connection, *, service_name: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE service_name=?"
        params.append(service_name)
    rows = conn.execute(
        f"""
        SELECT cluster_id, service_name, log_level, canonical_fingerprint,
               representative_template, representative_message, algorithm,
               member_count, total_occurrence_count, avg_pattern_similarity,
               min_pattern_similarity, avg_semantic_similarity,
               max_semantic_similarity, known_status, hybrid_vector_json,
               hybrid_vector_schema_version, status
        FROM pattern_clusters
        {where}
        ORDER BY total_occurrence_count DESC, member_count DESC, cluster_id ASC
        LIMIT ?
        """,
        [*params, limit],
    ).fetchall()
    clusters: list[dict[str, Any]] = []
    for row in rows:
        cluster_id = str(row[0])
        members = [
            {
                "fingerprint": str(member[0]),
                "role": str(member[1]),
                "pattern_similarity": float(member[2] or 0),
                "semantic_similarity": float(member[3] or 0),
                "hybrid_score": float(member[4] or 0),
                "match_type": str(member[5]),
                "occurrence_count": int(member[6] or 0),
            }
            for member in conn.execute(
                """
                SELECT fingerprint, role, pattern_similarity, semantic_similarity,
                       hybrid_score, match_type, occurrence_count
                FROM pattern_cluster_members
                WHERE cluster_id=?
                ORDER BY role='canonical' DESC, occurrence_count DESC, fingerprint ASC
                """,
                (cluster_id,),
            ).fetchall()
        ]
        links = [
            {
                "source_cluster_id": str(link[0]),
                "target_cluster_id": str(link[1]),
                "pattern_similarity": float(link[2] or 0),
                "semantic_similarity": float(link[3] or 0),
                "hybrid_score": float(link[4] or 0),
                "link_type": str(link[5]),
            }
            for link in conn.execute(
                """
                SELECT source_cluster_id, target_cluster_id, pattern_similarity,
                       semantic_similarity, hybrid_score, link_type
                FROM pattern_cluster_links
                WHERE source_cluster_id=? OR target_cluster_id=?
                ORDER BY semantic_similarity DESC, pattern_similarity DESC
                """,
                (cluster_id, cluster_id),
            ).fetchall()
        ]
        clusters.append(
            {
                "cluster_id": cluster_id,
                "service_name": str(row[1]),
                "log_level": str(row[2]),
                "canonical_fingerprint": str(row[3]),
                "representative_template": str(row[4]),
                "representative_message": str(row[5]),
                "algorithm": str(row[6]),
                "member_count": int(row[7] or 0),
                "total_occurrence_count": int(row[8] or 0),
                "avg_pattern_similarity": float(row[9] or 0),
                "min_pattern_similarity": float(row[10] or 0),
                "avg_semantic_similarity": float(row[11] or 0),
                "max_semantic_similarity": float(row[12] or 0),
                "known_status": str(row[13] or ""),
                "hybrid_vector": [
                    float(item)
                    for item in _load_json_list(str(row[14] or "[]"))
                    if isinstance(item, (int, float))
                ],
                "hybrid_vector_schema_version": str(row[15] or ""),
                "status": str(row[16] or ""),
                "members": members,
                "links": links,
            }
        )
    return clusters


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
    pair_scores: dict[tuple[str, str], float] = {}
    for index, matches in enumerate(match_groups):
        if index >= len(groups):
            continue
        source = str(groups[index].get("fingerprint") or "")
        source_group = lookup.get(source)
        if not source or source_group is None:
            continue
        for match in matches:
            target = _fingerprint_from_match(match)
            target_group = lookup.get(target)
            if (
                not target_group
                or target == source
                or target_group.get("service_name") != source_group.get("service_name")
                or str(target_group.get("log_level") or "").upper()
                != str(source_group.get("log_level") or "").upper()
            ):
                continue
            match = _match_with_group_context(match, target_group)
            pattern_similarity = _pattern_similarity(source_group, match)
            match = {
                **match,
                "pattern_similarity": pattern_similarity,
                "hybrid_similarity": pattern_similarity,
                "raw_similarity": match.get("similarity"),
            }
            pattern_similarity = float(
                match.get("pattern_similarity") or match.get("hybrid_similarity") or 0
            )
            pair_scores[(source, target)] = max(
                pair_scores.get((source, target), 0.0),
                pattern_similarity,
            )
            if pattern_similarity < PATTERN_DUPLICATE_SIMILARITY_THRESHOLD:
                continue
            edges[source].add(target)
            edges[target].add(source)

    components = _connected_duplicate_components(edges, lookup)
    seen_keys = {
        tuple(sorted(str(item.get("fingerprint") or "") for item in component))
        for component in components
    }
    for component in _hdbscan_duplicate_groups(groups, pair_scores):
        key = tuple(sorted(str(item.get("fingerprint") or "") for item in component))
        if key and key not in seen_keys:
            components.append(component)
            seen_keys.add(key)
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
    scored = [
        m
        for m in matches
        if m.get("pattern_similarity") is not None
        or m.get("hybrid_similarity") is not None
        or m.get("similarity") is not None
    ]
    if not scored:
        return None
    return max(scored, key=_match_score)


def _match_score(match: dict[str, Any]) -> float:
    for key in ("pattern_similarity", "hybrid_similarity", "similarity"):
        if match.get(key) is not None:
            return float(match.get(key) or 0)
    return 0.0


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

    approved_matches = _with_hybrid_similarity(item, approved_matches)
    observed_matches = _with_hybrid_similarity(item, observed_matches)
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
    best_score = _match_score(best_match) if best_match else 0.0
    if (
        best_match
        and best_score >= PATTERN_KNOWN_SIMILARITY_THRESHOLD
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
            "similarity_score": best_score,
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
                "drain_template": str(
                    item.get("drain_template")
                    or drain_log_template(str(item.get("message") or ""))
                ),
                "message_template": str(item.get("message_template") or ""),
                "normalized_message": str(item.get("normalized_message") or ""),
                "occurrence_count": int(item.get("occurrence_count") or 0),
                "risk_score": int(item.get("risk_score") or 0),
                "anomaly_count": int(item.get("anomaly_count") or 0),
                "pattern_status": str(item.get("pattern_status") or ""),
                "hybrid_vector_schema_version": HYBRID_VECTOR_SCHEMA_VERSION,
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
    if bucket_size == "30min":
        minute = 30 if parsed.minute >= 30 else 0
        return parsed.replace(minute=minute, second=0, microsecond=0).isoformat(
            timespec="seconds"
        )
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
) -> str:
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
    return bucket


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


MetricBucket = tuple[str, str, str]


def _metric_bucket_where(
    alias: str, buckets: set[MetricBucket]
) -> tuple[str, list[Any]]:
    if not buckets:
        return "", []
    clauses: list[str] = []
    params: list[Any] = []
    for svc, bucket_start, bucket_size in sorted(buckets):
        clauses.append(
            f"({alias}.service_name=? AND {alias}.bucket_start=? AND {alias}.bucket_size=?)"
        )
        params.extend([svc, bucket_start, bucket_size])
    return f"WHERE {' OR '.join(clauses)}", params


def _recent_metric_buckets(
    conn: sqlite3.Connection,
    *,
    service_name: str | None,
    limit: int = TIME_WINDOW_RECENT_RECALC_LIMIT,
) -> set[MetricBucket]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE service_name=?"
        params.append(service_name)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT DISTINCT service_name, bucket_start, bucket_size
        FROM pattern_time_series_metrics
        {where}
        ORDER BY bucket_size DESC, bucket_start DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return {(str(row[0]), str(row[1]), str(row[2])) for row in rows}


def _top_fingerprints_by_window(
    conn: sqlite3.Connection, buckets: set[MetricBucket]
) -> dict[MetricBucket, list[dict[str, Any]]]:
    where_sql, params = _metric_bucket_where("pt", buckets)
    if not where_sql:
        return {}
    rows = conn.execute(
        f"""
        WITH ranked AS (
            SELECT
                pt.service_name,
                pt.bucket_start,
                pt.bucket_size,
                pt.fingerprint,
                pt.total_count,
                ROW_NUMBER() OVER (
                    PARTITION BY pt.service_name, pt.bucket_start, pt.bucket_size
                    ORDER BY pt.total_count DESC, pt.fingerprint ASC
                ) AS rn
            FROM pattern_time_series_metrics pt
            {where_sql}
        )
        SELECT service_name, bucket_start, bucket_size, fingerprint, total_count
        FROM ranked
        WHERE rn <= 5
        ORDER BY service_name, bucket_start, bucket_size, rn
        """,
        params,
    ).fetchall()
    grouped: dict[MetricBucket, list[dict[str, Any]]] = {}
    for svc, bucket_start, bucket_size, fingerprint, count in rows:
        key = (str(svc), str(bucket_start), str(bucket_size))
        grouped.setdefault(key, []).append(
            {"fingerprint": str(fingerprint), "count": int(count or 0)}
        )
    return grouped


def _upsert_event_time_windows(
    conn: sqlite3.Connection,
    *,
    service_name: str | None,
    dirty_buckets: set[MetricBucket] | None = None,
) -> list[dict[str, Any]]:
    target_buckets = set(dirty_buckets or set())
    if not target_buckets:
        target_buckets = _recent_metric_buckets(conn, service_name=service_name)
    if not target_buckets:
        return []

    where_sql, params = _metric_bucket_where("pt", target_buckets)
    top_by_window = _top_fingerprints_by_window(conn, target_buckets)
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
        {where_sql}
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
        top_fingerprints = top_by_window.get((svc, bucket_start, bucket_size), [])
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
        windows.append(window)
    conn.executemany(
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
        [
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
                _json_list(window["top_fingerprints"]),
            )
            for window in windows
        ],
    )
    return windows


def _fetch_event_time_windows(
    conn: sqlite3.Connection,
    *,
    service_name: str | None,
    limit: int = TIME_WINDOW_RETURN_LIMIT,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE service_name=?"
        params.append(service_name)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            window_id, service_name, bucket_start, bucket_size,
            total_events, error_events, warn_events, info_events,
            unique_fingerprints, known_fingerprint_count, new_fingerprint_count,
            anomaly_count, max_risk_score, top_fingerprints_json
        FROM event_time_windows
        {where}
        ORDER BY bucket_size DESC, bucket_start DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "window_id": str(row[0]),
            "service_name": str(row[1]),
            "bucket_start": str(row[2]),
            "bucket_size": str(row[3]),
            "total_events": int(row[4] or 0),
            "error_events": int(row[5] or 0),
            "warn_events": int(row[6] or 0),
            "info_events": int(row[7] or 0),
            "unique_fingerprints": int(row[8] or 0),
            "known_fingerprint_count": int(row[9] or 0),
            "new_fingerprint_count": int(row[10] or 0),
            "anomaly_count": int(row[11] or 0),
            "max_risk_score": int(row[12] or 0),
            "top_fingerprints": [
                item
                for item in _load_json_list(str(row[13] or "[]"))
                if isinstance(item, dict)
            ],
        }
        for row in rows
    ]


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
        vectors.append(vector)
    conn.executemany(
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
        [
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
            )
            for vector in vectors
        ],
    )
    return vectors


def _fetch_system_state_vectors(
    conn: sqlite3.Connection,
    *,
    service_name: str | None,
    limit: int = TIME_WINDOW_RETURN_LIMIT,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE service_name=?"
        params.append(service_name)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            vector_id, scope_key, service_name, bucket_start, bucket_size,
            feature_schema_version, features_json, vector_json, label, incident_id
        FROM system_state_vectors
        {where}
        ORDER BY bucket_size DESC, bucket_start DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "vector_id": str(row[0]),
            "scope_key": str(row[1]),
            "service_name": str(row[2]),
            "bucket_start": str(row[3]),
            "bucket_size": str(row[4]),
            "feature_schema_version": str(row[5]),
            "features": _load_json_dict(str(row[6] or "{}")),
            "vector": [
                float(item)
                for item in _load_json_list(str(row[7] or "[]"))
                if isinstance(item, (int, float))
            ],
            "label": str(row[8]),
            "incident_id": str(row[9] or ""),
        }
        for row in rows
    ]


def _trajectory_id(
    service_name: str,
    bucket_size: str,
    window_length: int,
    start_bucket: str,
    end_bucket: str,
) -> str:
    raw = f"{service_name}|{bucket_size}|{window_length}|{start_bucket}|{end_bucket}"
    return "TRJ-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14].upper()


def _trajectory_cluster_id(
    service_name: str, bucket_size: str, member_ids: list[str]
) -> str:
    raw = f"{service_name}|{bucket_size}|{'|'.join(sorted(member_ids))}"
    return "TC-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12].upper()


def _trajectory_step_vector(features: dict[str, Any]) -> list[float]:
    return [
        math.log1p(float(features.get("total_events") or 0)),
        float(features.get("error_ratio") or 0),
        float(features.get("warn_ratio") or 0),
        math.log1p(float(features.get("unique_fingerprint_count") or 0)),
        float(features.get("unique_fingerprint_ratio") or 0),
        float(features.get("new_fingerprint_ratio") or 0),
        math.log1p(float(features.get("anomaly_count") or 0)),
        float(features.get("max_risk_score") or 0) / 100.0,
    ]


def _trajectory_distance(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 1.0
    total = sum((float(a) - float(b)) ** 2 for a, b in zip(left, right, strict=False))
    return math.sqrt(total / max(1, len(left)))


def _fetch_state_vectors_for_trajectories(
    conn: sqlite3.Connection, *, service_name: str | None
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE service_name=?"
        params.append(service_name)
    rows = conn.execute(
        f"""
        SELECT
            vector_id, scope_key, service_name, bucket_start, bucket_size,
            feature_schema_version, features_json, vector_json, label, incident_id
        FROM system_state_vectors
        {where}
        ORDER BY service_name ASC, bucket_size ASC, bucket_start ASC
        """,
        params,
    ).fetchall()
    return [
        {
            "vector_id": str(row[0]),
            "scope_key": str(row[1]),
            "service_name": str(row[2]),
            "bucket_start": str(row[3]),
            "bucket_size": str(row[4]),
            "feature_schema_version": str(row[5]),
            "features": _load_json_dict(str(row[6] or "{}")),
            "vector": [
                float(item)
                for item in _load_json_list(str(row[7] or "[]"))
                if isinstance(item, (int, float))
            ],
            "label": str(row[8]),
            "incident_id": str(row[9] or ""),
        }
        for row in rows
    ]


def _event_window_lookup(
    conn: sqlite3.Connection, *, service_name: str | None
) -> dict[tuple[str, str, str], dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE service_name=?"
        params.append(service_name)
    rows = conn.execute(
        f"""
        SELECT service_name, bucket_start, bucket_size, top_fingerprints_json
        FROM event_time_windows
        {where}
        """,
        params,
    ).fetchall()
    return {
        (str(row[0]), str(row[1]), str(row[2])): {
            "top_fingerprints": [
                item
                for item in _load_json_list(str(row[3] or "[]"))
                if isinstance(item, dict)
            ]
        }
        for row in rows
    }


def _trajectory_top_fingerprints(
    items: list[dict[str, Any]],
    windows: dict[tuple[str, str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        key = (
            str(item.get("service_name") or ""),
            str(item.get("bucket_start") or ""),
            str(item.get("bucket_size") or ""),
        )
        for fp_item in windows.get(key, {}).get("top_fingerprints", []):
            fingerprint = str(fp_item.get("fingerprint") or "")
            if not fingerprint:
                continue
            counts[fingerprint] = counts.get(fingerprint, 0) + int(
                fp_item.get("count") or 0
            )
    return [
        {"fingerprint": fingerprint, "count": count}
        for fingerprint, count in sorted(
            counts.items(), key=lambda pair: (-pair[1], pair[0])
        )[:5]
    ]


def _trajectory_label(
    top_fingerprints: list[dict[str, Any]], labels: list[str], risk_delta: int
) -> str:
    fingerprints = [
        str(item.get("fingerprint") or "")
        for item in top_fingerprints[:3]
        if str(item.get("fingerprint") or "")
    ]
    if fingerprints:
        suffix = "escalation" if risk_delta >= 10 else "trajectory"
        return f"{' -> '.join(fingerprints)} {suffix}"
    compact_labels = [label for label in labels if label and label != "normal"]
    if compact_labels:
        return f"{' -> '.join(compact_labels[:3])} trajectory"
    return "normal trajectory"


def _build_trajectory_record(
    items: list[dict[str, Any]],
    windows: dict[tuple[str, str, str], dict[str, Any]],
) -> dict[str, Any]:
    service_name = str(items[0].get("service_name") or "")
    bucket_size = str(items[0].get("bucket_size") or "")
    start_bucket = str(items[0].get("bucket_start") or "")
    end_bucket = str(items[-1].get("bucket_start") or "")
    features_by_step = [
        _load_json_dict(_json_dict(item.get("features", {}))) for item in items
    ]
    risks = [int(features.get("max_risk_score") or 0) for features in features_by_step]
    labels = [str(item.get("label") or "normal") for item in items]
    flat_vector = [
        value
        for features in features_by_step
        for value in _trajectory_step_vector(features)
    ]
    top_fingerprints = _trajectory_top_fingerprints(items, windows)
    risk_delta = (risks[-1] if risks else 0) - (risks[0] if risks else 0)
    total_events = sum(int(features.get("total_events") or 0) for features in features_by_step)
    anomaly_count = sum(int(features.get("anomaly_count") or 0) for features in features_by_step)
    max_risk_score = max(risks, default=0)
    window_length = len(items)
    return {
        "trajectory_id": _trajectory_id(
            service_name, bucket_size, window_length, start_bucket, end_bucket
        ),
        "service_name": service_name,
        "bucket_size": bucket_size,
        "window_length": window_length,
        "start_bucket": start_bucket,
        "end_bucket": end_bucket,
        "vector_ids": [str(item.get("vector_id") or "") for item in items],
        "top_fingerprints": top_fingerprints,
        "features": {
            "start_label": labels[0] if labels else "normal",
            "end_label": labels[-1] if labels else "normal",
            "risk_delta": risk_delta,
            "total_events": total_events,
            "anomaly_count": anomaly_count,
            "max_risk_score": max_risk_score,
        },
        "flat_vector": flat_vector,
        "label": _trajectory_label(top_fingerprints, labels, risk_delta),
        "max_risk_score": max_risk_score,
        "anomaly_count": anomaly_count,
        "total_events": total_events,
    }


def _upsert_trajectories(
    conn: sqlite3.Connection, *, service_name: str | None
) -> list[dict[str, Any]]:
    if service_name:
        conn.execute("DELETE FROM trajectories WHERE service_name=?", (service_name,))
    else:
        conn.execute("DELETE FROM trajectories")

    vectors = _fetch_state_vectors_for_trajectories(conn, service_name=service_name)
    if not vectors:
        return []
    windows = _event_window_lookup(conn, service_name=service_name)
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for vector in vectors:
        key = (str(vector.get("service_name") or ""), str(vector.get("bucket_size") or ""))
        buckets.setdefault(key, []).append(vector)

    trajectories: list[dict[str, Any]] = []
    for items in buckets.values():
        if not items:
            continue
        window_length = min(TRAJECTORY_FIXED_WINDOW_LENGTH, len(items))
        if window_length <= 0:
            continue
        for index in range(0, len(items) - window_length + 1):
            trajectories.append(
                _build_trajectory_record(items[index : index + window_length], windows)
            )

    conn.executemany(
        """
        INSERT INTO trajectories(
            trajectory_id, service_name, bucket_size, window_length,
            start_bucket, end_bucket, vector_ids_json, top_fingerprints_json,
            features_json, flat_vector_json, label, max_risk_score,
            anomaly_count, total_events, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(service_name, bucket_size, window_length, start_bucket, end_bucket)
        DO UPDATE SET
            vector_ids_json=excluded.vector_ids_json,
            top_fingerprints_json=excluded.top_fingerprints_json,
            features_json=excluded.features_json,
            flat_vector_json=excluded.flat_vector_json,
            label=excluded.label,
            max_risk_score=excluded.max_risk_score,
            anomaly_count=excluded.anomaly_count,
            total_events=excluded.total_events,
            updated_at=CURRENT_TIMESTAMP
        """,
        [
            (
                item["trajectory_id"],
                item["service_name"],
                item["bucket_size"],
                item["window_length"],
                item["start_bucket"],
                item["end_bucket"],
                _json_list(item["vector_ids"]),
                _json_list(item["top_fingerprints"]),
                _json_dict(item["features"]),
                _json_list(item["flat_vector"]),
                item["label"],
                item["max_risk_score"],
                item["anomaly_count"],
                item["total_events"],
            )
            for item in trajectories
        ],
    )
    return trajectories


def _fetch_trajectories(
    conn: sqlite3.Connection,
    *,
    service_name: str | None,
    limit: int = TRAJECTORY_RETURN_LIMIT,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE service_name=?"
        params.append(service_name)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            trajectory_id, service_name, bucket_size, window_length,
            start_bucket, end_bucket, vector_ids_json, top_fingerprints_json,
            features_json, flat_vector_json, label, max_risk_score,
            anomaly_count, total_events
        FROM trajectories
        {where}
        ORDER BY end_bucket DESC, bucket_size DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "trajectory_id": str(row[0]),
            "service_name": str(row[1]),
            "bucket_size": str(row[2]),
            "window_length": int(row[3] or 0),
            "start_bucket": str(row[4]),
            "end_bucket": str(row[5]),
            "vector_ids": [str(item) for item in _load_json_list(str(row[6] or "[]"))],
            "top_fingerprints": [
                item
                for item in _load_json_list(str(row[7] or "[]"))
                if isinstance(item, dict)
            ],
            "features": _load_json_dict(str(row[8] or "{}")),
            "flat_vector": [
                float(item)
                for item in _load_json_list(str(row[9] or "[]"))
                if isinstance(item, (int, float))
            ],
            "label": str(row[10] or ""),
            "max_risk_score": int(row[11] or 0),
            "anomaly_count": int(row[12] or 0),
            "total_events": int(row[13] or 0),
        }
        for row in rows
    ]


def _hdbscan_trajectory_labels(vectors: list[list[float]]) -> list[int]:
    if len(vectors) < TRAJECTORY_CLUSTER_MIN_SIZE:
        return []
    try:
        numpy = importlib.import_module("numpy")
        hdbscan = importlib.import_module("hdbscan")
        clusterer = hdbscan.HDBSCAN(
            metric="euclidean",
            min_cluster_size=TRAJECTORY_CLUSTER_MIN_SIZE,
            min_samples=TRAJECTORY_CLUSTER_MIN_SAMPLES,
            cluster_selection_method="eom",
        )
        labels = clusterer.fit_predict(numpy.array(vectors))
    except Exception:  # noqa: BLE001
        return []
    return [int(label) for label in labels]


def _fallback_trajectory_groups(
    trajectories: list[dict[str, Any]]
) -> list[list[dict[str, Any]]]:
    buckets: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for item in trajectories:
        top = [
            str(fp_item.get("fingerprint") or "")
            for fp_item in item.get("top_fingerprints", [])[:2]
            if str(fp_item.get("fingerprint") or "")
        ]
        key = (
            str(item.get("service_name") or ""),
            str(item.get("bucket_size") or ""),
            " -> ".join(top) or str(item.get("label") or "normal"),
        )
        buckets.setdefault(key, []).append(item)
    return [
        group
        for group in buckets.values()
        if len(group) >= 2 or any(int(item.get("max_risk_score") or 0) >= 70 for item in group)
    ]


def _representative_trajectory(items: list[dict[str, Any]]) -> dict[str, Any]:
    return max(
        items,
        key=lambda item: (
            int(item.get("max_risk_score") or 0),
            int(item.get("anomaly_count") or 0),
            int(item.get("total_events") or 0),
            str(item.get("end_bucket") or ""),
        ),
    )


def _cluster_top_fingerprints(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in items:
        for fp_item in item.get("top_fingerprints", []):
            fingerprint = str(fp_item.get("fingerprint") or "")
            if not fingerprint:
                continue
            counts[fingerprint] = counts.get(fingerprint, 0) + int(
                fp_item.get("count") or 0
            )
    return [
        {"fingerprint": fingerprint, "count": count}
        for fingerprint, count in sorted(
            counts.items(), key=lambda pair: (-pair[1], pair[0])
        )[:5]
    ]


def _trajectory_cluster_record(
    *,
    items: list[dict[str, Any]],
    algorithm: str,
) -> dict[str, Any]:
    representative = _representative_trajectory(items)
    member_ids = [str(item.get("trajectory_id") or "") for item in items]
    rep_vector = [
        float(item)
        for item in representative.get("flat_vector", [])
        if isinstance(item, (int, float))
    ]
    distances = [
        _trajectory_distance(rep_vector, item.get("flat_vector", []))
        for item in items
        if item.get("trajectory_id") != representative.get("trajectory_id")
    ]
    top_fingerprints = _cluster_top_fingerprints(items)
    label = _trajectory_label(
        top_fingerprints,
        [str(item.get("label") or "") for item in items],
        max(int(item.get("features", {}).get("risk_delta") or 0) for item in items),
    )
    return {
        "cluster_id": _trajectory_cluster_id(
            str(representative.get("service_name") or ""),
            str(representative.get("bucket_size") or ""),
            member_ids,
        ),
        "service_name": str(representative.get("service_name") or ""),
        "bucket_size": str(representative.get("bucket_size") or ""),
        "algorithm": algorithm,
        "representative_trajectory_id": str(representative.get("trajectory_id") or ""),
        "member_trajectory_ids": member_ids,
        "top_fingerprints": top_fingerprints,
        "label": label,
        "member_count": len(items),
        "max_risk_score": max(int(item.get("max_risk_score") or 0) for item in items),
        "anomaly_count": sum(int(item.get("anomaly_count") or 0) for item in items),
        "avg_distance": round(sum(distances) / len(distances), 6) if distances else 0.0,
    }


def _upsert_trajectory_clusters(
    conn: sqlite3.Connection, *, service_name: str | None
) -> list[dict[str, Any]]:
    if service_name:
        conn.execute("DELETE FROM trajectory_clusters WHERE service_name=?", (service_name,))
    else:
        conn.execute("DELETE FROM trajectory_clusters")

    trajectories = list(reversed(_fetch_trajectories(conn, service_name=service_name, limit=500)))
    buckets: dict[tuple[str, str, int], list[dict[str, Any]]] = {}
    for item in trajectories:
        if not item.get("flat_vector"):
            continue
        key = (
            str(item.get("service_name") or ""),
            str(item.get("bucket_size") or ""),
            int(item.get("window_length") or 0),
        )
        buckets.setdefault(key, []).append(item)

    clusters: list[dict[str, Any]] = []
    for items in buckets.values():
        bucket_clusters: list[dict[str, Any]] = []
        labels = _hdbscan_trajectory_labels(
            [item.get("flat_vector", []) for item in items]
        )
        if labels and len(labels) == len(items):
            by_label: dict[int, list[dict[str, Any]]] = {}
            for label, item in zip(labels, items, strict=False):
                if label < 0:
                    continue
                by_label.setdefault(label, []).append(item)
            bucket_clusters.extend(
                _trajectory_cluster_record(items=group, algorithm="fixed_window_hdbscan")
                for group in by_label.values()
                if len(group) >= 2
            )
        if not bucket_clusters:
            bucket_clusters.extend(
                _trajectory_cluster_record(
                    items=group, algorithm="fixed_window_signature_fallback"
                )
                for group in _fallback_trajectory_groups(items)
            )
        clusters.extend(bucket_clusters)

    conn.executemany(
        """
        INSERT INTO trajectory_clusters(
            cluster_id, service_name, bucket_size, algorithm,
            representative_trajectory_id, member_trajectory_ids_json,
            top_fingerprints_json, label, member_count, max_risk_score,
            anomaly_count, avg_distance, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(cluster_id) DO UPDATE SET
            algorithm=excluded.algorithm,
            representative_trajectory_id=excluded.representative_trajectory_id,
            member_trajectory_ids_json=excluded.member_trajectory_ids_json,
            top_fingerprints_json=excluded.top_fingerprints_json,
            label=excluded.label,
            member_count=excluded.member_count,
            max_risk_score=excluded.max_risk_score,
            anomaly_count=excluded.anomaly_count,
            avg_distance=excluded.avg_distance,
            updated_at=CURRENT_TIMESTAMP
        """,
        [
            (
                item["cluster_id"],
                item["service_name"],
                item["bucket_size"],
                item["algorithm"],
                item["representative_trajectory_id"],
                _json_list(item["member_trajectory_ids"]),
                _json_list(item["top_fingerprints"]),
                item["label"],
                item["member_count"],
                item["max_risk_score"],
                item["anomaly_count"],
                item["avg_distance"],
            )
            for item in clusters
        ],
    )
    return clusters


def _fetch_trajectory_clusters(
    conn: sqlite3.Connection,
    *,
    service_name: str | None,
    limit: int = TRAJECTORY_CLUSTER_RETURN_LIMIT,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if service_name:
        where = "WHERE service_name=?"
        params.append(service_name)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            cluster_id, service_name, bucket_size, algorithm,
            representative_trajectory_id, member_trajectory_ids_json,
            top_fingerprints_json, label, member_count, max_risk_score,
            anomaly_count, avg_distance
        FROM trajectory_clusters
        {where}
        ORDER BY max_risk_score DESC, member_count DESC, cluster_id ASC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            "cluster_id": str(row[0]),
            "service_name": str(row[1]),
            "bucket_size": str(row[2]),
            "algorithm": str(row[3]),
            "representative_trajectory_id": str(row[4]),
            "member_trajectory_ids": [
                str(item) for item in _load_json_list(str(row[5] or "[]"))
            ],
            "top_fingerprints": [
                item
                for item in _load_json_list(str(row[6] or "[]"))
                if isinstance(item, dict)
            ],
            "label": str(row[7] or ""),
            "member_count": int(row[8] or 0),
            "max_risk_score": int(row[9] or 0),
            "anomaly_count": int(row[10] or 0),
            "avg_distance": float(row[11] or 0),
        }
        for row in rows
    ]


def _nearest_trajectory_patterns(
    trajectories: list[dict[str, Any]],
    clusters: list[dict[str, Any]],
    *,
    limit: int = TRAJECTORY_NEAREST_RETURN_LIMIT,
) -> list[dict[str, Any]]:
    if not trajectories or not clusters:
        return []
    latest = max(trajectories, key=lambda item: str(item.get("end_bucket") or ""))
    latest_vector = latest.get("flat_vector", [])
    by_id = {str(item.get("trajectory_id") or ""): item for item in trajectories}
    matches: list[dict[str, Any]] = []
    for cluster in clusters:
        representative = by_id.get(str(cluster.get("representative_trajectory_id") or ""))
        if not representative:
            continue
        distance = _trajectory_distance(latest_vector, representative.get("flat_vector", []))
        matches.append(
            {
                "trajectory_id": latest.get("trajectory_id"),
                "cluster_id": cluster.get("cluster_id"),
                "label": cluster.get("label"),
                "similarity": round(max(0.0, 1.0 - distance), 6),
                "distance": round(distance, 6),
                "representative_trajectory_id": representative.get("trajectory_id"),
                "top_fingerprints": cluster.get("top_fingerprints", []),
            }
        )
    return sorted(matches, key=lambda item: item["similarity"], reverse=True)[:limit]


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
            if current - previous >= timedelta(days=RECURRENCE_MIN_SILENCE_DAYS):
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
            "drain_template": "",
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
    include_time_windows: bool = True,
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
            include_time_windows,
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
        dirty_metric_buckets: set[MetricBucket] = set()
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
                    "drain_template": "",
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
                for bucket_size in TIME_SERIES_BUCKET_SIZES:
                    bucket = _increment_pattern_metric(
                        conn,
                        service_name=svc,
                        fingerprint=fp,
                        level=level,
                        created_at=created,
                        bucket_size=bucket_size,
                    )
                    dirty_metric_buckets.add((str(svc), bucket, bucket_size))
        group_items = _apply_drain_templates(list(groups.values()))
        groups = {str(item.get("fingerprint") or ""): item for item in group_items}
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
    visible_groups = _attach_detection_features(
        visible_groups,
        impacts=impacts,
        anomalies=anomalies,
    )
    duplicate_candidates = detect_duplicate_pattern_candidates(visible_groups)
    with sqlite3.connect(db_path) as model_conn:
        ensure_schema(model_conn)
        _upsert_fingerprint_merge_groups(
            model_conn,
            candidates=duplicate_candidates,
            groups_by_fingerprint={str(g["fingerprint"]): g for g in visible_groups},
        )
        pattern_clusters = build_pattern_clusters(model_conn, visible_groups)
        merge_groups = _fetch_fingerprint_merge_groups(
            model_conn, status="pending", limit=50
        )
        if include_time_windows:
            updated_event_time_windows = _upsert_event_time_windows(
                model_conn,
                service_name=service_name,
                dirty_buckets=dirty_metric_buckets,
            )
            _upsert_system_state_vectors(
                model_conn, windows=updated_event_time_windows
            )
            _upsert_trajectories(model_conn, service_name=service_name)
            _upsert_trajectory_clusters(model_conn, service_name=service_name)
            event_time_windows = _fetch_event_time_windows(
                model_conn, service_name=service_name
            )
            system_state_vectors = _fetch_system_state_vectors(
                model_conn, service_name=service_name
            )
            all_trajectories = _fetch_trajectories(
                model_conn, service_name=service_name, limit=500
            )
            trajectories = all_trajectories[:TRAJECTORY_RETURN_LIMIT]
            trajectory_clusters = _fetch_trajectory_clusters(
                model_conn, service_name=service_name
            )
            nearest_trajectory_patterns = _nearest_trajectory_patterns(
                all_trajectories, trajectory_clusters
            )
        else:
            event_time_windows = []
            system_state_vectors = []
            trajectories = []
            trajectory_clusters = []
            nearest_trajectory_patterns = []
        model_conn.commit()
    latest_event_time_windows = event_time_windows
    latest_system_state_vectors = system_state_vectors
    latest_trajectories = trajectories
    latest_trajectory_clusters = trajectory_clusters
    latest_nearest_trajectory_patterns = nearest_trajectory_patterns
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
    daily_analysis_date = date_start or datetime.utcnow().date().isoformat()
    semantic_clusters = build_semantic_log_clusters(
        visible_groups,
        recommendations=visible_recs,
        impacts=visible_impacts,
        anomalies=anomalies,
    )
    with sqlite3.connect(db_path) as semantic_conn:
        ensure_schema(semantic_conn)
        _upsert_semantic_log_clusters(
            semantic_conn,
            clusters=semantic_clusters,
            analysis_date=daily_analysis_date,
            service_name=service_name,
        )
        semantic_clusters = _fetch_semantic_log_clusters(
            semantic_conn,
            service_name=service_name,
            analysis_date=daily_analysis_date,
            limit=100,
        )
        semantic_conn.commit()
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
        "pattern_clusters": pattern_clusters,
        "semantic_clusters": semantic_clusters,
        "duplicate_pattern_candidates": duplicate_candidates,
        "fingerprint_merge_groups": merge_groups,
        "event_time_windows": latest_event_time_windows,
        "system_state_vectors": latest_system_state_vectors,
        "trajectories": latest_trajectories,
        "trajectory_clusters": latest_trajectory_clusters,
        "nearest_trajectory_patterns": latest_nearest_trajectory_patterns,
        "summary": {
            "total_logs": total_logs,
            "processed_new_logs": len(rows),
            "total_fingerprints": len(visible_groups),
            "known_patterns": known_count,
            "new_patterns": new_count,
            "pattern_clusters": len(pattern_clusters),
            "semantic_clusters": len(semantic_clusters),
            "trajectories": len(latest_trajectories),
            "trajectory_clusters": len(latest_trajectory_clusters),
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


def fetch_knowledge_cards_by_ids(card_ids: list[str]) -> list[dict[str, Any]]:
    """Return Knowledge Cards for the given IDs, preserving input order."""
    ordered_ids = list(dict.fromkeys(str(card_id) for card_id in card_ids if card_id))
    if not ordered_ids:
        return []
    placeholders = ",".join("?" for _ in ordered_ids)
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
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
            WHERE kc.card_id IN ({placeholders})
            """,
            ordered_ids,
        ).fetchall()
    cards_by_id = {
        str(row[0]): {
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
    }
    return [cards_by_id[card_id] for card_id in ordered_ids if card_id in cards_by_id]


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
        pattern_id = int(cur.lastrowid)
        cur.execute(
            """
            INSERT INTO log_analysis_results(
                fingerprint, category, sub_category, is_known_pattern,
                is_new_pattern, pattern_status, match_source,
                similar_fingerprint, similarity_score
            ) VALUES (?, ?, ?, 1, 0, 'known_exact', 'known_patterns', '', NULL)
            ON CONFLICT(fingerprint) DO UPDATE SET
                category=excluded.category,
                sub_category=excluded.sub_category,
                is_known_pattern=1,
                is_new_pattern=0,
                pattern_status='known_exact',
                match_source='known_patterns',
                similar_fingerprint='',
                similarity_score=NULL
            """,
            (fingerprint, category, sub_category),
        )
        conn.commit()
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
    _PIPELINE_CACHE.clear()
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
