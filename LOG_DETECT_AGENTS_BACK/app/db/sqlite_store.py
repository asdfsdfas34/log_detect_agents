"""SQLite-backed log access helpers."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any


def _resolve_db_path() -> str:
    """Resolve SQLite database path from environment variables."""

    sqlite_path = os.getenv("SQLITE_PATH", "").strip()
    if sqlite_path:
        return sqlite_path

    # Backward compatibility for existing deployments that only define POSTGRESQL_URL.
    legacy = os.getenv("POSTGRESQL_URL", "").strip()
    if legacy:
        return legacy

    return "./data/logs.db"


def fetch_recent_logs(*, service_name: str | None, limit: int = 20) -> list[str]:
    """Read recent log messages from local SQLite storage.

    Expected table schema:
      service_logs(service_name TEXT, message TEXT, created_at TEXT)
    """

    db_path = _resolve_db_path()
    if not db_path:
        return []

    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return []

    query = (
        "SELECT message FROM service_logs "
        "WHERE (? IS NULL OR service_name = ?) "
        "ORDER BY datetime(created_at) DESC "
        "LIMIT ?"
    )

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, (service_name, service_name, limit))
            rows = cur.fetchall()
        return [str(row[0]) for row in rows]
    except Exception:
        return []


def fetch_recent_log_entries(*, service_names: list[str] | None, limit: int = 200) -> list[dict[str, Any]]:
    """Read recent structured logs from SQLite storage.

    Expected table schema:
      service_logs(service_name TEXT, level TEXT, message TEXT, created_at TEXT, stack_trace TEXT)
    """

    db_path = _resolve_db_path()
    if not db_path:
        return []

    try:
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        return []

    normalized_services = [s for s in (service_names or []) if s]
    where_sql = ""
    params: list[Any] = []
    if normalized_services:
        placeholders = ",".join("?" for _ in normalized_services)
        where_sql = f"WHERE service_name IN ({placeholders})"
        params.extend(normalized_services)

    query = (
        "SELECT service_name, COALESCE(level, ''), message, created_at, COALESCE(stack_trace, '') "
        "FROM service_logs "
        f"{where_sql} "
        "ORDER BY datetime(created_at) DESC "
        "LIMIT ?"
    )
    params.append(limit)

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
    except Exception:
        return []

    return [
        {
            "system": str(row[0]),
            "level": str(row[1] or "INFO").upper(),
            "message": str(row[2]),
            "timestamp": str(row[3]),
            "stack_trace": str(row[4]) if row[4] else "",
        }
        for row in rows
    ]


def save_log_analysis(*, goal: str, service_name: str, analysis: str) -> None:
    """Persist log analysis output to SQLite."""

    db_path = _resolve_db_path()
    if not db_path:
        return

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS log_analyses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goal TEXT NOT NULL,
                service_name TEXT NOT NULL,
                analysis TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            "INSERT INTO log_analyses(goal, service_name, analysis) VALUES (?, ?, ?)",
            (goal, service_name, analysis),
        )
        conn.commit()


def fetch_latest_log_analyses(*, service_names: list[str] | None, limit: int = 20) -> list[dict[str, str]]:
    """Load latest persisted analyses for impact evaluation."""

    db_path = _resolve_db_path()
    if not db_path:
        return []

    normalized_services = [s for s in (service_names or []) if s]
    where_sql = ""
    params: list[Any] = []
    if normalized_services:
        placeholders = ",".join("?" for _ in normalized_services)
        where_sql = f"WHERE service_name IN ({placeholders})"
        params.extend(normalized_services)

    query = (
        "SELECT goal, service_name, analysis, created_at "
        "FROM log_analyses "
        f"{where_sql} "
        "ORDER BY datetime(created_at) DESC "
        "LIMIT ?"
    )
    params.append(limit)

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
    except Exception:
        return []

    return [
        {
            "goal": str(row[0]),
            "service_name": str(row[1]),
            "analysis": str(row[2]),
            "created_at": str(row[3]),
        }
        for row in rows
    ]


def save_impact_evaluation(*, service_name: str, risk_score: int, confidence: str, rationale: str) -> None:
    """Persist impact evaluation output to SQLite."""

    db_path = _resolve_db_path()
    if not db_path:
        return

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS impact_evaluations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT NOT NULL,
                risk_score INTEGER NOT NULL,
                confidence TEXT NOT NULL,
                rationale TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cur.execute(
            """
            INSERT INTO impact_evaluations(service_name, risk_score, confidence, rationale)
            VALUES (?, ?, ?, ?)
            """,
            (service_name, risk_score, confidence, rationale),
        )
        conn.commit()
