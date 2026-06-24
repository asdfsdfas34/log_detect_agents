"""Generate daily service log rows by sampling existing SQLite data."""

from __future__ import annotations

import argparse
import random
import re
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

from app.db.sqlite_store import _resolve_db_path

NUMERIC_RE = re.compile(r"\b\d+\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create synthetic service_logs rows from existing rows. "
            "Defaults to today through 7 days ago, 2,000 rows per day."
        )
    )
    parser.add_argument("--db-path", default="", help="SQLite DB path. Defaults to .env.dev SQLITE_PATH.")
    parser.add_argument("--end-date", default="", help="End date in YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--days-back", type=int, default=7, help="Inclusive days back from end date.")
    parser.add_argument("--per-day", type=int, default=2000, help="Rows to create for each date.")
    parser.add_argument("--seed", type=int, default=20260624, help="Random seed for repeatable data.")
    return parser.parse_args()


def _random_timestamp(day: date) -> str:
    seconds = random.randint(0, 86_399)
    micros = random.randint(0, 999_999)
    return datetime.combine(day, time.min) + timedelta(seconds=seconds, microseconds=micros)


def _mutate_text(value: str | None, row_number: int) -> str:
    if not value:
        return ""

    text = UUID_RE.sub(lambda _: str(uuid4()), value)

    def replace_number(match: re.Match[str]) -> str:
        raw = match.group(0)
        if len(raw) >= 4:
            return str(random.randint(1000, 999999))
        upper = max(9, 10 ** len(raw) - 1)
        return str(random.randint(1, upper))

    text = NUMERIC_RE.sub(replace_number, text)
    if "request_id" not in text.lower() and random.random() < 0.18:
        text = f"{text} request_id={uuid4().hex[:12]}"
    if random.random() < 0.10:
        text = f"{text} sample_seq={row_number}"
    return text


def _load_source_rows(conn: sqlite3.Connection) -> list[tuple[str, str, str, str]]:
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(service_name, ''), 'unknown-service'),
            COALESCE(NULLIF(level, ''), 'INFO'),
            COALESCE(message, ''),
            COALESCE(stack_trace, '')
        FROM service_logs
        WHERE COALESCE(message, '') != ''
        """
    ).fetchall()
    if not rows:
        raise ValueError("service_logs has no source rows to sample from.")
    return [(str(a), str(b).upper(), str(c), str(d)) for a, b, c, d in rows]


def generate_rows(
    *, source_rows: list[tuple[str, str, str, str]], target_date: date, per_day: int
) -> list[tuple[str, str, str, str, str]]:
    generated: list[tuple[str, str, str, str, str]] = []
    for index in range(per_day):
        service_name, level, message, stack_trace = random.choice(source_rows)
        created_at = _random_timestamp(target_date).isoformat(timespec="milliseconds")
        generated.append(
            (
                service_name,
                level,
                _mutate_text(message, index),
                _mutate_text(stack_trace, index),
                created_at,
            )
        )
    return generated


def main() -> None:
    args = _parse_args()
    random.seed(args.seed)

    db_path = Path(args.db_path or _resolve_db_path())
    end_date = date.fromisoformat(args.end_date) if args.end_date else date.today()
    dates = [end_date - timedelta(days=offset) for offset in range(args.days_back, -1, -1)]

    with sqlite3.connect(db_path) as conn:
        source_rows = _load_source_rows(conn)
        total = 0
        for target_date in dates:
            rows = generate_rows(
                source_rows=source_rows,
                target_date=target_date,
                per_day=args.per_day,
            )
            conn.executemany(
                """
                INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            total += len(rows)
        conn.commit()

    print(f"Inserted {total} rows into {db_path}")
    print(f"Date range: {dates[0].isoformat()} .. {dates[-1].isoformat()}")
    print(f"Rows per day: {args.per_day}")


if __name__ == "__main__":
    main()
