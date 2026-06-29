"""Generate service_logs rows for one date from registered fingerprint patterns."""

from __future__ import annotations

import argparse
import random
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.db.sqlite_store import _resolve_db_path  # noqa: E402

NUMERIC_RE = re.compile(r"\b\d+\b")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


@dataclass(frozen=True)
class PatternRow:
    service_name: str
    level: str
    message: str
    stack_trace: str
    occurrence_count: int


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create synthetic service_logs rows for one date by sampling the "
            "registered fingerprints table. This inserts rows only; it does not "
            "change the database schema."
        )
    )
    parser.add_argument(
        "--date",
        required=True,
        help="Target service_logs date in YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of service_logs rows to insert for the target date.",
    )
    parser.add_argument(
        "--service-name",
        default="",
        help="Optional service_name filter for source fingerprint patterns.",
    )
    parser.add_argument(
        "--db-path",
        default="",
        help="SQLite DB path. Defaults to .env.dev SQLITE_PATH.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260629,
        help="Random seed for repeatable generated logs.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print a preview without inserting rows.",
    )
    return parser.parse_args()


def _random_timestamp(target_date: date) -> str:
    seconds = random.randint(0, 86_399)
    micros = random.randint(0, 999_999)
    value = datetime.combine(target_date, time.min) + timedelta(
        seconds=seconds, microseconds=micros
    )
    return value.isoformat(timespec="milliseconds")


def _replacement_value() -> str:
    if random.random() < 0.25:
        return uuid4().hex[:12]
    return str(random.randint(1, 999_999))


def _random_email() -> str:
    return f"user{random.randint(1, 99999)}@example{random.randint(1, 20)}.com"


def _random_url() -> str:
    return (
        f"https://api{random.randint(1, 9)}.example.com/"
        f"orders/{random.randint(1000, 999999)}"
    )


def _random_date_time() -> str:
    day = date(
        random.randint(2024, 2026),
        random.randint(1, 12),
        random.randint(1, 28),
    )
    value = datetime.combine(
        day,
        time(
            random.randint(0, 23),
            random.randint(0, 59),
            random.randint(0, 59),
        ),
    )
    return value.isoformat(sep=" ", timespec="seconds")


def _random_path() -> str:
    folders = ["Logs", "Temp", "Upload", "Batch", "AppData"]
    names = ["request.log", "payload.json", "trace.txt", "cache.dat", "result.csv"]
    return f"C:\\{random.choice(folders)}\\{random.choice(names)}"


def _contextual_wildcard_value(prefix: str, suffix: str) -> str:
    local_prefix = prefix[-40:]
    key_match = re.search(r"([A-Za-z_][\w.-]*)\s*(?:[:=]|\s)\s*$", local_prefix)
    key = key_match.group(1).lower() if key_match else ""
    context = f"{key} {suffix[:16]}".lower()
    if "email" in key or "mail" in key:
        return _random_email()
    if "url" in key or "uri" in key:
        return _random_url()
    if "path" in key or "\\" in prefix[-8:]:
        return _random_path()
    if any(token in key for token in ("date", "time", "created", "updated")):
        return _random_date_time()
    if any(token in key for token in ("guid", "uuid")):
        return str(uuid4())
    if any(
        token in key
        for token in ("id", "seq", "no", "number", "code", "status", "line")
    ):
        return str(random.randint(1, 999_999))
    if suffix.startswith("@"):
        return f"user{random.randint(1, 99999)}"
    if suffix.startswith("://") or "http" in context:
        return "https"
    if suffix.startswith("."):
        return str(random.randint(1, 999))
    return _replacement_value()


def _replace_wildcards(value: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in re.finditer(r"\*", value):
        parts.append(value[cursor : match.start()])
        parts.append(
            _contextual_wildcard_value(value[: match.start()], value[match.end() :])
        )
        cursor = match.end()
    parts.append(value[cursor:])
    return "".join(parts)


def _mutate_text(value: str, row_number: int) -> str:
    if not value:
        return ""

    text = UUID_RE.sub(lambda _: str(uuid4()), value)
    text = _replace_wildcards(text)

    def replace_number(match: re.Match[str]) -> str:
        raw = match.group(0)
        if len(raw) >= 4:
            return str(random.randint(1000, 999999))
        upper = max(9, 10 ** len(raw) - 1)
        return str(random.randint(1, upper))

    text = NUMERIC_RE.sub(replace_number, text)
    if "request_id" not in text.lower() and random.random() < 0.20:
        text = f"{text} request_id={uuid4().hex[:12]}"
    if random.random() < 0.08:
        text = f"{text} sample_seq={row_number}"
    return text


def _load_patterns(
    conn: sqlite3.Connection, *, service_name: str = ""
) -> list[PatternRow]:
    params: list[str] = []
    where = "WHERE COALESCE(message, '') != ''"
    if service_name:
        where += " AND service_name = ?"
        params.append(service_name)

    rows = conn.execute(
        f"""
        SELECT
            COALESCE(NULLIF(service_name, ''), 'unknown-service'),
            COALESCE(NULLIF(log_level, ''), 'INFO'),
            COALESCE(message, ''),
            COALESCE(stacktrace, ''),
            COALESCE(occurrence_count, 1)
        FROM fingerprints
        {where}
        """,
        params,
    ).fetchall()

    patterns = [
        PatternRow(
            service_name=str(row[0]),
            level=str(row[1]).upper(),
            message=str(row[2]),
            stack_trace=str(row[3]),
            occurrence_count=max(1, int(row[4] or 1)),
        )
        for row in rows
    ]
    if not patterns:
        target = f" for service_name={service_name!r}" if service_name else ""
        raise ValueError(f"No registered fingerprint patterns found{target}.")
    return patterns


def _weighted_pattern(patterns: list[PatternRow]) -> PatternRow:
    weights = [pattern.occurrence_count for pattern in patterns]
    return random.choices(patterns, weights=weights, k=1)[0]


def generate_rows(
    *, patterns: list[PatternRow], target_date: date, count: int
) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for index in range(count):
        pattern = _weighted_pattern(patterns)
        rows.append(
            (
                pattern.service_name,
                pattern.level,
                _mutate_text(pattern.message, index),
                _mutate_text(pattern.stack_trace, index),
                _random_timestamp(target_date),
            )
        )
    return rows


def main() -> None:
    args = _parse_args()
    if args.count <= 0:
        raise ValueError("--count must be greater than 0.")

    random.seed(args.seed)
    target_date = date.fromisoformat(args.date)
    db_path = Path(args.db_path or _resolve_db_path())

    with sqlite3.connect(db_path) as conn:
        patterns = _load_patterns(conn, service_name=args.service_name.strip())
        rows = generate_rows(
            patterns=patterns,
            target_date=target_date,
            count=args.count,
        )
        if not args.dry_run:
            conn.executemany(
                """
                INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                rows,
            )
            conn.commit()

    action = "Previewed" if args.dry_run else "Inserted"
    print(f"{action} {len(rows)} service_logs rows for {target_date.isoformat()}")
    print(f"Source patterns: {len(patterns)}")
    print(f"Database: {db_path}")
    if rows:
        sample = rows[0]
        print(
            "Sample: "
            f"service_name={sample[0]}, level={sample[1]}, "
            f"created_at={sample[4]}, message={sample[2][:120]}"
        )


if __name__ == "__main__":
    main()
