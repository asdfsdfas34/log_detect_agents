import os
import sqlite3
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.scenario_store import ensure_schema  # noqa: E402


def get_db_path() -> str:
    """Read SQLITE_PATH from .env.dev and resolve it from the backend root."""

    return _resolve_db_path()


def _resolve_db_path() -> str:
    """Resolve SQLite database path from environment variables."""

    load_dotenv(PROJECT_ROOT / ".env.dev")

    db_path = os.getenv("SQLITE_PATH")
    if not db_path:
        raise ValueError("SQLITE_PATH is not configured.")

    path = Path(db_path)
    if not path.is_absolute():
        path = PROJECT_ROOT / path

    return str(path)


def _resolve_excel_path(excel_file: str) -> str:
    """Resolve Excel paths from cwd first, then from this script directory."""

    path = Path(excel_file)
    if path.is_absolute():
        return str(path)

    cwd_candidate = Path.cwd() / path
    if cwd_candidate.exists():
        return str(cwd_candidate)

    return str(Path(__file__).resolve().parent / path)


def import_excel_to_sqlite(excel_file: str) -> None:
    """Import Excel rows into the service_logs SQLite table."""

    db_path = _resolve_db_path()
    excel_path = _resolve_excel_path(excel_file)

    df = pd.read_excel(excel_path)

    required_columns = [
        "service_name",
        "level",
        "message",
        "created_at",
        "stack_trace",
    ]

    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Required columns are missing: {missing}")

    rows = [
        (
            str(row["service_name"]),
            str(row["level"]),
            str(row["message"]),
            str(row["created_at"]),
            str(row["stack_trace"]),
        )
        for _, row in df.iterrows()
    ]

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.executemany(
            """
            INSERT INTO service_logs
            (
                service_name,
                level,
                message,
                created_at,
                stack_trace
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()

    print(f"Imported {len(rows)} rows into {db_path}")


if __name__ == "__main__":
    import_excel_to_sqlite("./log_raw_edit_daily3.xlsx")
