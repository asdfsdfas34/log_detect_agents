"""SQLite-backed log access helpers."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


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
