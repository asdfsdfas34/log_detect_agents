"""Delete SQLite table rows without changing the database schema.

This script intentionally uses DELETE statements only. It does not DROP,
ALTER, recreate tables, or delete the database file.
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.db.sqlite_store import _resolve_db_path

TABLES = [
    "processed_log_offsets",
    "pattern_time_series_metrics",
    "log_processing_state",
    "impact_evaluations",
    "anomaly_results",
    "log_analysis_results",
    "fingerprints",
    "knowledge_cards",
    "exception_registry",
    "known_patterns",
    "recommendation_results",
    "impact_evaluation_history",
    "log_analyses",
    "service_logs",
]


def existing_tables(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type='table' AND name NOT LIKE 'sqlite_%'
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    row = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()
    return int(row[0] or 0)


def clear_table_data(*, db_path: Path, apply: bool) -> list[tuple[str, int]]:
    deleted: list[tuple[str, int]] = []
    with sqlite3.connect(db_path) as conn:
        present = existing_tables(conn)
        target_tables = [table for table in TABLES if table in present]
        for table in target_tables:
            row_count = count_rows(conn, table)
            deleted.append((table, row_count))
            if apply:
                conn.execute(f'DELETE FROM "{table}"')
        if apply:
            conn.commit()
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Delete rows from known SQLite tables without changing schema."
    )
    parser.add_argument(
        "--db-path",
        default=_resolve_db_path(),
        help="SQLite DB path. Defaults to the configured SQLITE_PATH.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete rows. Without this flag, only prints a dry-run summary.",
    )
    args = parser.parse_args()

    db_path = Path(args.db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")

    rows = clear_table_data(db_path=db_path, apply=args.yes)
    mode = "deleted" if args.yes else "would delete"
    print(f"Database: {db_path}")
    for table, count in rows:
        print(f"{mode} {count} rows from {table}")
    if not args.yes:
        print("Dry run only. Re-run with --yes to delete data.")


if __name__ == "__main__":
    main()
