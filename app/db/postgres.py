from __future__ import annotations

import os
from typing import List, Optional

try:
    import psycopg
except Exception:  # pragma: no cover - optional runtime dependency
    psycopg = None


def fetch_recent_logs(*, service_name: Optional[str], limit: int = 20) -> List[str]:
    if psycopg is None:
        return []
    dsn = os.getenv("POSTGRESQL_URL", "").strip()
    if not dsn:
        return []

    query = (
        "SELECT message FROM service_logs "
        "WHERE (%s IS NULL OR service_name = %s) "
        "ORDER BY created_at DESC "
        "LIMIT %s"
    )

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, (service_name, service_name, limit))
                rows = cur.fetchall()
        return [str(row[0]) for row in rows]
    except Exception:
        return []
