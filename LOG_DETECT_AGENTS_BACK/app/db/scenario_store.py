"""Scenario database pipeline for log fingerprinting, detection, risk, and knowledge reuse."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from app.db.chroma_store import save_analysis_document
from app.db.sqlite_store import _resolve_db_path

NUMERIC_RE = re.compile(r"\b\d+\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
JSON_STRING_VALUE_RE = re.compile(r'(:\s*)"([^"\\]*(?:\\.[^"\\]*)*)"')
JSON_LITERAL_VALUE_RE = re.compile(
    r"(:\s*)(-?\d+(?:\.\d+)?|true|false|null)(?=\s*[,}])",
    re.IGNORECASE,
)
ASSIGNED_VALUE_RE = re.compile(
    r"(\b[A-Za-z_][\w.-]*\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;}\]]+)"
)
IDENTIFIER_KEY_VALUE_RE = re.compile(
    r"(\b[A-Za-z_][\w.-]*(?:ID|Id|Status|Code|No|Number|Seq|Date|Time|Token|Key|"
    r"GUID|UUID)\b\s+)(?![:=])([^\s,;}\]]+)",
)
KOREAN_HONORIFIC_NUMBER_RE = re.compile(r"(?<=\S)\d+(?=님)")
LEADING_LIST_MARKER_RE = re.compile(r"^\s*\d+\s*[.)]\s*")
LEADING_COMPONENT_DOT_RE = re.compile(r"^\s*\.(?=[A-Za-z_])")
WHITESPACE_RE = re.compile(r"\s+")

SERVICE_CRITICALITY = {
    "login-service": "HIGH",
    "board-service": "MEDIUM",
    "batch-service": "LOW",
}
CRITICALITY_SCORE = {"HIGH": 30, "MEDIUM": 15, "LOW": 5}
LEVEL_SCORE = {"ERROR": 50, "WARN": 20, "INFO": 5}


def normalize_log_text(value: str) -> str:
    """Replace volatile values so equal log templates share one fingerprint."""
    text = value or ""
    text = LEADING_LIST_MARKER_RE.sub("", text)
    text = LEADING_COMPONENT_DOT_RE.sub("", text)
    text = UUID_RE.sub("*", text)
    text = JSON_STRING_VALUE_RE.sub(r'\1"*"', text)
    text = JSON_LITERAL_VALUE_RE.sub(r"\1*", text)
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
    return WHITESPACE_RE.sub(" ", text).strip()


def normalize_stacktrace(value: str) -> str:
    """Normalize stack traces with the same volatile-token rules used for messages."""
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
        """)

    for column, definition in {
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
            cur.execute(f"ALTER TABLE exception_registry ADD COLUMN {column} {definition}")
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


def run_detection_pipeline(service_name: str | None = None) -> dict[str, Any]:
    """Run SC-001~SC-005 over stored logs and return dashboard-ready summary data."""
    db_path = _resolve_db_path()
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        where = "WHERE service_name=?" if service_name else ""
        params = (service_name,) if service_name else ()
        rows = cur.execute(
            f"SELECT service_name, level, message, COALESCE(stack_trace,''), created_at FROM service_logs {where}",
            params,
        ).fetchall()
        groups: dict[str, dict[str, Any]] = {}
        for svc, level, msg, stack, created in rows:
            normalized_message = normalize_log_text(msg)
            fp = fingerprint_id(svc, level.upper(), msg, stack)
            item = groups.setdefault(
                fp,
                {
                    "fingerprint": fp,
                    "occurrence_count": 0,
                    "log_level": level.upper(),
                    "message": msg,
                    "normalized_message": normalized_message,
                    "stacktrace": normalize_stacktrace(stack),
                    "service_name": svc,
                    "first_seen": created,
                    "last_seen": created,
                },
            )
            item["occurrence_count"] += 1
            item["first_seen"] = min(item["first_seen"], created)
            item["last_seen"] = max(item["last_seen"], created)
        for g in groups.values():
            cur.execute(
                "REPLACE INTO fingerprints VALUES (:fingerprint,:occurrence_count,:log_level,:message,:stacktrace,:service_name,:first_seen,:last_seen)",
                g,
            )
        ignored = {
            r[0]
            for r in cur.execute(
                "SELECT fingerprint FROM exception_registry"
            ).fetchall()
        }
        ignored_signatures = set()
        for row in cur.execute(
            """
            SELECT
                er.normalized_message,
                er.log_level,
                er.message,
                fp.message,
                fp.log_level
            FROM exception_registry er
            LEFT JOIN fingerprints fp ON fp.fingerprint = er.fingerprint
            """
        ).fetchall():
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
        for fp, g in groups.items():
            is_ignored = fp in ignored or (
                g["normalized_message"],
                g["log_level"],
            ) in ignored_signatures
            cat, sub = classify(g["message"], g["stacktrace"])
            known = (
                cur.execute(
                    "SELECT 1 FROM known_patterns WHERE fingerprint=? OR sub_category=? LIMIT 1",
                    (fp, sub),
                ).fetchone()
                is not None
            )
            cur.execute(
                "REPLACE INTO log_analysis_results(fingerprint,category,sub_category,is_known_pattern,is_new_pattern) VALUES (?,?,?,?,?)",
                (fp, cat, sub, int(known), int(not known)),
            )
            baseline = max(
                1,
                math.ceil(
                    g["occurrence_count"] / (3 if g["occurrence_count"] >= 25 else 1)
                ),
            )
            spike_ratio = round((g["occurrence_count"] / baseline) * 100, 1)
            anomaly = (not known) or spike_ratio >= 200
            if is_ignored:
                anomaly = False
            severity = "HIGH" if spike_ratio >= 200 or not known else "LOW"
            cur.execute(
                "REPLACE INTO anomaly_results VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)",
                (
                    fp,
                    int(anomaly),
                    spike_ratio if anomaly else 0,
                    severity if anomaly else "NONE",
                    "NEW_ERROR" if not known else "SPIKE",
                ),
            )
            if anomaly:
                anomalies.append(
                    {
                        "system": g["service_name"],
                        "severity": severity,
                        "pattern": fp,
                        "message": g["message"],
                        "spike_ratio": spike_ratio,
                    }
                )
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
            r.update({"fingerprint": fp, "sub_category": sub})
            recs.append(r)
        conn.commit()
        total_logs = len(rows)
        known_count = cur.execute(
            "SELECT COUNT(*) FROM log_analysis_results WHERE is_known_pattern=1"
        ).fetchone()[0]
        new_count = cur.execute(
            "SELECT COUNT(*) FROM log_analysis_results WHERE is_new_pattern=1"
        ).fetchone()[0]
        exception_count = cur.execute(
            "SELECT COUNT(*) FROM exception_registry"
        ).fetchone()[0]
    visible_groups = []
    ignored_fingerprints = set(ignored)
    for fp, group in groups.items():
        if fp in ignored or (
            group["normalized_message"],
            group["log_level"],
        ) in ignored_signatures:
            ignored_fingerprints.add(fp)
            continue
        visible_groups.append(group)
    visible_impacts = [
        impact for impact in impacts if impact["fingerprint"] not in ignored_fingerprints
    ]
    visible_recs = [rec for rec in recs if rec["fingerprint"] not in ignored_fingerprints]
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
    return {
        "fingerprints": visible_groups,
        "anomalies": anomalies,
        "impacts": visible_impacts,
        "recommendations": visible_recs,
        "recommendation": top_rec,
        "summary": {
            "total_logs": total_logs,
            "total_fingerprints": len(visible_groups),
            "known_patterns": known_count,
            "new_patterns": new_count,
            "anomalies_detected": len(anomalies),
            "exception_registered_count": exception_count,
            "risk_score": top_impact["risk_score"],
            "risk_level": top_impact["risk_level"],
            "detection_status": "Detected" if top_impact["detected"] else "Normal",
        },
    }



def _json_list(items: list[str]) -> str:
    return json.dumps(items, ensure_ascii=False)


def _json_dict(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, sort_keys=True)


def _load_json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in value] if isinstance(value, list) else []


def _load_json_dict(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


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
    summary = f"{service_name}에서 {sub_category} 패턴이 {occurrence_count}회 관측되었습니다."
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
            "created_at": str(row[6]),
            "message": str(row[7]),
            "log_level": str(row[8]),
            "service_name": str(row[9]),
            "title": str(row[10]),
            "summary": str(row[11]),
            "symptoms": _load_json_list(str(row[12])),
            "evidence_text": str(row[13]),
            "root_cause": str(row[14]),
            "remediation_steps": _load_json_list(str(row[15])),
            "verification_steps": _load_json_list(str(row[16])),
            "prevention_steps": _load_json_list(str(row[17])),
            "metadata": _load_json_dict(str(row[18])),
            "rag_document": str(row[19]),
            "embedding_status": str(row[20]),
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
    fp: str, cause: str, recommendation: str, action: str, confidence: str
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
                title, summary, symptoms, evidence_text, root_cause, remediation_steps,
                verification_steps, prevention_steps, metadata_json, rag_document, embedding_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                card_id,
                fp,
                cause,
                recommendation,
                action,
                confidence,
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
