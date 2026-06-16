"""Scenario database pipeline for log fingerprinting, detection, risk, and knowledge reuse."""

from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from app.db.sqlite_store import _resolve_db_path

NUMERIC_RE = re.compile(r"\b\d+\b")

SERVICE_CRITICALITY = {
    "login-service": "HIGH",
    "board-service": "MEDIUM",
    "batch-service": "LOW",
}
CRITICALITY_SCORE = {"HIGH": 30, "MEDIUM": 15, "LOW": 5}
LEVEL_SCORE = {"ERROR": 50, "WARN": 20, "INFO": 5}


def normalize_stacktrace(value: str) -> str:
    """Replace volatile numeric values with '*' so equal errors share one fingerprint."""
    return NUMERIC_RE.sub("*", value or "")


def fingerprint_id(service_name: str, level: str, message: str, stacktrace: str) -> str:
    """Create a stable short fingerprint identifier from normalized error content."""
    raw = f"{service_name}|{level}|{message}|{normalize_stacktrace(stacktrace)}"
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS knowledge_cards (
            card_id TEXT PRIMARY KEY,
            fingerprint TEXT NOT NULL,
            cause TEXT NOT NULL,
            recommendation TEXT NOT NULL,
            action TEXT NOT NULL,
            confidence TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        """)
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
            fp = fingerprint_id(svc, level.upper(), msg, stack)
            item = groups.setdefault(
                fp,
                {
                    "fingerprint": fp,
                    "occurrence_count": 0,
                    "log_level": level.upper(),
                    "message": msg,
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
        anomalies = []
        impacts = []
        recs = []
        for fp, g in groups.items():
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
            if fp in ignored:
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
            if fp in ignored:
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
    top_impact = max(
        impacts,
        key=lambda x: x["risk_score"],
        default={"risk_score": 0, "risk_level": "Low", "detected": False},
    )
    top_rec = (
        recs[0] if recs else {"cause": "-", "recommendation": "-", "confidence": "LOW"}
    )
    return {
        "fingerprints": list(groups.values()),
        "anomalies": anomalies,
        "impacts": impacts,
        "recommendations": recs,
        "recommendation": top_rec,
        "summary": {
            "total_logs": total_logs,
            "total_fingerprints": len(groups),
            "known_patterns": known_count,
            "new_patterns": new_count,
            "anomalies_detected": len(anomalies),
            "exception_registered_count": exception_count,
            "risk_score": top_impact["risk_score"],
            "risk_level": top_impact["risk_level"],
            "detection_status": "Detected" if top_impact["detected"] else "Normal",
        },
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
            where_sql = "WHERE fingerprint = ?"
            params.append(fingerprint)
        params.append(limit)
        rows = conn.execute(
            """
            SELECT card_id, fingerprint, cause, recommendation, action, confidence, created_at
            FROM knowledge_cards
            {where_sql}
            ORDER BY datetime(created_at) DESC, card_id DESC
            LIMIT ?
            """.format(where_sql=where_sql),
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
            where_sql = "WHERE fingerprint = ?"
            params.append(fingerprint)
        params.append(limit)
        rows = conn.execute(
            """
            SELECT fingerprint, reason, created_at
            FROM exception_registry
            {where_sql}
            ORDER BY datetime(created_at) DESC, fingerprint DESC
            LIMIT ?
            """.format(where_sql=where_sql),
            params,
        ).fetchall()
    return [
        {
            "fingerprint": str(row[0]),
            "reason": str(row[1]),
            "created_at": str(row[2]),
        }
        for row in rows
    ]


def register_exception(fp: str, reason: str) -> None:
    """Register a fingerprint that should be ignored by risk and anomaly detection."""
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        conn.execute(
            "REPLACE INTO exception_registry(fingerprint, reason) VALUES (?, ?)",
            (fp, reason),
        )
        conn.commit()


def approve_result(
    fp: str, cause: str, recommendation: str, action: str, confidence: str
) -> str:
    """Persist an approved AI/rule result as a reusable Knowledge Card."""
    card_id = "KC-" + datetime.utcnow().strftime("%H%M%S%f")[:9]
    with sqlite3.connect(_resolve_db_path()) as conn:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO knowledge_cards(card_id,fingerprint,cause,recommendation,action,confidence) VALUES (?,?,?,?,?,?)",
            (card_id, fp, cause, recommendation, action, confidence),
        )
        conn.commit()
    return card_id
