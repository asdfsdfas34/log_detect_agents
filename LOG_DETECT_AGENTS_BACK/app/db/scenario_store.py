"""Scenario database pipeline for log fingerprinting, detection, risk, and knowledge reuse."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlsplit, urlunsplit

from app.db.chroma_store import (
    find_similar_analysis_documents,
    find_similar_pattern_clusters,
    save_analysis_document,
    save_pattern_cluster,
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
_PIPELINE_CACHE: dict[tuple[str | None, int | None, int, str], dict[str, Any]] = {}
KNOWN_SIMILARITY_THRESHOLD = 0.88


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


def _pattern_status(
    *,
    conn: sqlite3.Connection,
    item: dict[str, Any],
    existing_fingerprints: set[str],
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

    context = _pattern_cluster_context(item)
    approved_match = _top_similarity(
        [
            match
            for match in find_similar_analysis_documents(query=context)
            if (match.get("metadata") or {}).get("source")
            in {"approved_recommendation", "known_pattern"}
            or str(match.get("id") or "").startswith("knowledge-card:")
            or str(match.get("id") or "").startswith("known-pattern:")
        ]
    )
    observed_match = _top_similarity(
        [
            match
            for match in find_similar_pattern_clusters(query=context)
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
        return {
            "pattern_status": "observed_existing",
            "match_source": "fingerprints",
            "similar_fingerprint": "",
            "similarity_score": None,
        }

    return {
        "pattern_status": "new_pattern",
        "match_source": "",
        "similar_fingerprint": "",
        "similarity_score": None,
    }


def _upsert_pattern_cluster(item: dict[str, Any]) -> None:
    save_pattern_cluster(
        doc_id=f"{item.get('service_name')}:{item.get('fingerprint')}",
        text=_pattern_cluster_context(item),
        metadata={
            "service_name": str(item.get("service_name") or ""),
            "fingerprint": str(item.get("fingerprint") or ""),
            "log_level": str(item.get("log_level") or ""),
            "normalized_message": str(item.get("normalized_message") or ""),
            "occurrence_count": int(item.get("occurrence_count") or 0),
            "pattern_status": str(item.get("pattern_status") or ""),
        },
    )


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
    conn: sqlite3.Connection, service_name: str | None, cutoff: str | None
) -> tuple[int, str]:
    where_parts = []
    params: list[Any] = []
    if service_name:
        where_parts.append("service_name=?")
        params.append(service_name)
    if cutoff:
        where_parts.append("created_at>=?")
        params.append(cutoff)
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


def _anomaly_type_for(
    *,
    group: dict[str, Any],
    known: bool,
    spike_ratio: float,
    metric: dict[str, Any],
) -> tuple[bool, str, str]:
    latest = int(metric.get("latest_count") or 0)
    baseline = float(metric.get("baseline_count") or 0)
    status = str(group.get("pattern_status") or "")
    if status == "new_pattern":
        return (
            True,
            "NEW_ERROR" if group.get("log_level") == "ERROR" else "NEW_PATTERN",
            "HIGH",
        )
    if status == "known_similar":
        return True, "SIMILAR_CASE_MATCH", "MEDIUM"
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
    if baseline >= 1 and latest >= baseline * 2:
        return True, "SPIKE", "HIGH"
    if baseline >= 4 and latest <= baseline * 0.5:
        return True, "DROP", "MEDIUM"
    if spike_ratio >= 200:
        return True, "SPIKE", "HIGH"
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


def run_detection_pipeline(
    service_name: str | None = None, *, days_back: int | None = None
) -> dict[str, Any]:
    """Run SC-001~SC-005 over stored logs and return dashboard-ready summary data."""
    db_path = _resolve_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cutoff = (
            (datetime.utcnow() - timedelta(days=days_back)).isoformat(
                timespec="seconds"
            )
            if days_back is not None
            else None
        )
        signature_count, signature_max_created = _pipeline_signature(
            conn, service_name, cutoff
        )
        last_rowid = _last_processed_rowid(conn, service_name)
        cache_key = (
            service_name,
            days_back,
            signature_count,
            last_rowid,
            signature_max_created,
        )
        cached = _PIPELINE_CACHE.get(cache_key)
        if cached is not None:
            return copy.deepcopy(cached)

        where_parts = ["rowid > ?"]
        params: list[Any] = [last_rowid]
        if service_name:
            where_parts.append("service_name=?")
            params.append(service_name)
        if cutoff:
            where_parts.append("created_at>=?")
            params.append(cutoff)
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
        groups: dict[str, dict[str, Any]] = {}
        max_rowid = last_rowid
        max_created = ""
        for rowid, svc, level, msg, stack, created in rows:
            max_rowid = max(max_rowid, int(rowid))
            max_created = max(max_created, str(created))
            normalized_message = normalize_log_text(msg)
            fp = fingerprint_id(svc, level.upper(), msg, stack)
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
                    "occurrence_count": int(existing[0] or 0) if existing else 0,
                    "log_level": level.upper(),
                    "message": str(existing[3] or msg) if existing else msg,
                    "normalized_message": normalized_message,
                    "stacktrace": (
                        str(existing[4] or normalize_stacktrace(stack))
                        if existing
                        else normalize_stacktrace(stack)
                    ),
                    "service_name": svc,
                    "first_seen": str(existing[1] or created) if existing else created,
                    "last_seen": str(existing[2] or created) if existing else created,
                    "previous_last_seen": str(existing[2] or "") if existing else "",
                },
            )
            item["occurrence_count"] += 1
            item["first_seen"] = min(item["first_seen"], created)
            item["last_seen"] = max(item["last_seen"], created)
            for bucket_size in ("day", "hour"):
                _increment_pattern_metric(
                    conn,
                    service_name=svc,
                    fingerprint=fp,
                    level=level,
                    created_at=created,
                    bucket_size=bucket_size,
                )
            cur.execute(
                """
                INSERT OR IGNORE INTO processed_log_offsets(service_name, log_rowid, fingerprint)
                VALUES (?, ?, ?)
                """,
                (svc, int(rowid), fp),
            )
        for g in groups.values():
            g.update(
                _pattern_status(
                    conn=conn,
                    item=g,
                    existing_fingerprints=existing_fingerprints,
                )
            )
        for g in groups.values():
            _upsert_pattern_cluster(g)
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
        if rows:
            _save_processing_state(conn, service_name, max_rowid, max_created)

        all_groups = _load_fingerprint_groups(conn, service_name)
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
            if anomaly:
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
            continue
        visible_groups.append(group)
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
    result = {
        "fingerprints": visible_groups,
        "anomalies": anomalies,
        "impacts": visible_impacts,
        "recommendations": visible_recs,
        "recommendation": top_rec,
        "summary": {
            "total_logs": total_logs,
            "processed_new_logs": len(rows),
            "total_fingerprints": len(visible_groups),
            "known_patterns": known_count,
            "new_patterns": new_count,
            "anomalies_detected": len(anomalies),
            "exception_registered_count": exception_count,
            "risk_score": top_impact["risk_score"],
            "risk_level": top_impact["risk_level"],
            "detection_status": "Detected" if anomalies else "Normal",
        },
    }
    _PIPELINE_CACHE[cache_key] = copy.deepcopy(result)
    return result


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
