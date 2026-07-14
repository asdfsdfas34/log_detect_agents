"""Idempotent 10-minute metric backfill for the RecFM Preview.

The main analysis pipeline only increments ``pattern_time_series_metrics`` for
raw logs it has not processed yet (tracked via ``processed_log_offsets``). Adding
``"10min"`` to ``TIME_SERIES_BUCKET_SIZES`` therefore only affects *future* logs;
historical logs that were already processed do not automatically get a 10-minute
aggregate.

This operator command recomputes the 10-minute ``pattern_time_series_metrics``
(and the 10-minute derived event windows / state vectors / trajectories /
clusters) directly from ``service_logs`` so the RecFM Preview can be inspected on
existing data.

Safety guarantees:

* Only the ``bucket_size='10min'`` metric rows are written. Existing
  ``30min`` / ``hour`` / ``day`` metric rows are never modified or deleted.
* Raw ``service_logs`` and ``processed_log_offsets`` are never modified.
* ChromaDB is never touched.
* Uses a stable key ``(service_name, fingerprint, bucket_start, '10min')`` and an
  UPSERT that SETs absolute counts, so re-running never double-counts.
* The same fingerprint / canonical-mapping logic as the pipeline is reused, so
  10-minute buckets line up with the existing 30min/hour/day buckets.

Usage (operator-triggered only; never runs automatically)::

    python backfill_10min_metrics.py --dry-run
    python backfill_10min_metrics.py --service-name billing-service
    python backfill_10min_metrics.py --date-start 2026-06-01 --date-end 2026-06-30

Backfill is intended to be tested against a temporary SQLite DB (``SQLITE_PATH``).
"""

from __future__ import annotations

import argparse
import sqlite3
from typing import Any

from app.db.scenario_store import (
    RECFM_BUCKET_SIZE,
    _bucket_start,
    _canonical_fingerprint,
    _known_pattern_signature_map,
    _upsert_event_time_windows,
    _upsert_system_state_vectors,
    _upsert_trajectories,
    _upsert_trajectory_clusters,
    ensure_schema,
    fingerprint_id,
)
from app.db.sqlite_store import _resolve_db_path


def _level_flags(level: str) -> tuple[int, int, int]:
    level_upper = str(level or "").upper()
    error = 1 if level_upper == "ERROR" else 0
    warn = 1 if level_upper in {"WARN", "WARNING"} else 0
    info = 1 if level_upper in {"INFO", "INFORMATION"} else 0
    return error, warn, info


def _aggregate_ten_minute_metrics(
    conn: sqlite3.Connection,
    *,
    service_name: str | None,
    date_start: str | None,
    date_end: str | None,
) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Recompute absolute 10-minute counts per (service, fingerprint, bucket)."""
    known_signature_map = _known_pattern_signature_map(conn)
    where_parts: list[str] = []
    params: list[Any] = []
    if service_name:
        where_parts.append("service_name=?")
        params.append(service_name)
    if date_start:
        where_parts.append("substr(created_at, 1, 10) >= ?")
        params.append(date_start)
    if date_end:
        where_parts.append("substr(created_at, 1, 10) <= ?")
        params.append(date_end)
    where = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    rows = conn.execute(
        f"""
        SELECT service_name, level, message, COALESCE(stack_trace, ''), created_at
        FROM service_logs {where}
        ORDER BY rowid ASC
        """,
        params,
    ).fetchall()

    aggregates: dict[tuple[str, str, str], dict[str, Any]] = {}
    for svc, level, msg, stack, created in rows:
        svc = str(svc or "")
        created = str(created or "")
        raw_fp = fingerprint_id(svc, str(level or "").upper(), str(msg or ""), str(stack or ""))
        fp = _canonical_fingerprint(
            conn,
            raw_fp,
            service_name=svc,
            log_level=str(level or ""),
            message=str(msg or ""),
            known_signature_map=known_signature_map,
        )
        bucket = _bucket_start(created, RECFM_BUCKET_SIZE)
        error, warn, info = _level_flags(str(level or ""))
        key = (svc, fp, bucket)
        record = aggregates.get(key)
        if record is None:
            record = {
                "total_count": 0,
                "error_count": 0,
                "warn_count": 0,
                "info_count": 0,
                "first_seen": created,
                "last_seen": created,
            }
            aggregates[key] = record
        record["total_count"] += 1
        record["error_count"] += error
        record["warn_count"] += warn
        record["info_count"] += info
        if created and (not record["first_seen"] or created < record["first_seen"]):
            record["first_seen"] = created
        if created and created > record["last_seen"]:
            record["last_seen"] = created
    return aggregates


def _upsert_absolute_metrics(
    conn: sqlite3.Connection,
    aggregates: dict[tuple[str, str, str], dict[str, Any]],
) -> None:
    """Write absolute 10-minute counts (idempotent, only touches '10min' rows)."""
    conn.executemany(
        """
        INSERT INTO pattern_time_series_metrics(
            service_name, fingerprint, bucket_start, bucket_size,
            total_count, error_count, warn_count, info_count, first_seen, last_seen
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(service_name, fingerprint, bucket_start, bucket_size)
        DO UPDATE SET
            total_count = excluded.total_count,
            error_count = excluded.error_count,
            warn_count = excluded.warn_count,
            info_count = excluded.info_count,
            first_seen = excluded.first_seen,
            last_seen = excluded.last_seen
        """,
        [
            (
                svc,
                fp,
                bucket,
                RECFM_BUCKET_SIZE,
                record["total_count"],
                record["error_count"],
                record["warn_count"],
                record["info_count"],
                record["first_seen"],
                record["last_seen"],
            )
            for (svc, fp, bucket), record in aggregates.items()
        ],
    )


def backfill_ten_minute_metrics(
    conn: sqlite3.Connection,
    *,
    service_name: str | None = None,
    date_start: str | None = None,
    date_end: str | None = None,
    dry_run: bool = False,
    rebuild_derived: bool = True,
) -> dict[str, Any]:
    """Backfill 10-minute metrics and (optionally) derived RecFM data.

    Returns a summary dict. When ``dry_run`` is True no rows are written.
    """
    ensure_schema(conn)
    aggregates = _aggregate_ten_minute_metrics(
        conn,
        service_name=service_name,
        date_start=date_start,
        date_end=date_end,
    )
    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "service_name": service_name,
        "date_start": date_start,
        "date_end": date_end,
        "metric_rows": len(aggregates),
        "total_events": sum(int(r["total_count"]) for r in aggregates.values()),
        "buckets": len({bucket for (_svc, _fp, bucket) in aggregates}),
        "services": len({svc for (svc, _fp, _bucket) in aggregates}),
    }
    if dry_run:
        summary["event_time_windows"] = 0
        summary["system_state_vectors"] = 0
        return summary

    _upsert_absolute_metrics(conn, aggregates)

    if rebuild_derived:
        dirty_buckets = {
            (svc, bucket, RECFM_BUCKET_SIZE)
            for (svc, _fp, bucket) in aggregates
        }
        windows = _upsert_event_time_windows(
            conn, service_name=service_name, dirty_buckets=dirty_buckets
        )
        vectors = _upsert_system_state_vectors(conn, windows=windows)
        # Trajectories/clusters are rebuilt deterministically from persisted
        # state vectors of all buckets (matching the normal pipeline). Existing
        # 30min/hour/day derived data is regenerated, never intentionally dropped.
        _upsert_trajectories(conn, service_name=service_name)
        _upsert_trajectory_clusters(conn, service_name=service_name)
        summary["event_time_windows"] = len(windows)
        summary["system_state_vectors"] = len(vectors)
    conn.commit()
    return summary


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Idempotent 10-minute metric backfill for the RecFM Preview.",
    )
    parser.add_argument(
        "--service-name",
        default=None,
        help="Only backfill this service (default: all services).",
    )
    parser.add_argument(
        "--date-start",
        default=None,
        help="Inclusive start date (YYYY-MM-DD) filter on created_at.",
    )
    parser.add_argument(
        "--date-end",
        default=None,
        help="Inclusive end date (YYYY-MM-DD) filter on created_at.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report counts without writing to the database.",
    )
    parser.add_argument(
        "--no-derived",
        action="store_true",
        help="Backfill metrics only; skip rebuilding derived 10min data.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_path = _resolve_db_path()
    with sqlite3.connect(db_path) as conn:
        summary = backfill_ten_minute_metrics(
            conn,
            service_name=args.service_name,
            date_start=args.date_start,
            date_end=args.date_end,
            dry_run=args.dry_run,
            rebuild_derived=not args.no_derived,
        )
    mode = "DRY-RUN (no writes)" if summary["dry_run"] else "WROTE"
    print(f"[backfill_10min_metrics] {mode} against {db_path}")
    print(f"  service_name       : {summary['service_name'] or '(all)'}")
    print(f"  date range         : {summary['date_start'] or '-'} .. {summary['date_end'] or '-'}")
    print(f"  10min metric rows  : {summary['metric_rows']}")
    print(f"  10min total events : {summary['total_events']}")
    print(f"  10min buckets      : {summary['buckets']}")
    print(f"  services           : {summary['services']}")
    if not summary["dry_run"]:
        print(f"  event_time_windows : {summary.get('event_time_windows', 0)}")
        print(f"  system_state_vecs  : {summary.get('system_state_vectors', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
