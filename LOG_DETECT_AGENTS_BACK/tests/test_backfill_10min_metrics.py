import sqlite3
from pathlib import Path

from app.db.scenario_store import ensure_schema, run_detection_pipeline
from backfill_10min_metrics import backfill_ten_minute_metrics


def _insert_logs(db_path: Path, service_name: str, timestamps: list[str]) -> None:
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES (?, 'ERROR', ?, '', ?)
            """,
            [(service_name, f"Payment failed at {ts}", ts) for ts in timestamps],
        )
        conn.commit()


def _metric_counts(db_path: Path, bucket_size: str) -> int:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(total_count), 0) FROM pattern_time_series_metrics "
            "WHERE bucket_size=?",
            (bucket_size,),
        ).fetchone()
    return int(row[0] or 0)


def test_backfill_creates_ten_minute_metrics_from_raw_logs(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    stamps = [f"2026-06-16T10:{minute:02d}:00" for minute in range(0, 60, 10)]
    _insert_logs(db_path, "billing-service", stamps)

    with sqlite3.connect(db_path) as conn:
        summary = backfill_ten_minute_metrics(conn)

    assert summary["total_events"] == 6
    assert _metric_counts(db_path, "10min") == 6
    with sqlite3.connect(db_path) as conn:
        windows = conn.execute(
            "SELECT COUNT(*) FROM event_time_windows WHERE bucket_size='10min'"
        ).fetchone()[0]
        vectors = conn.execute(
            "SELECT COUNT(*) FROM system_state_vectors WHERE bucket_size='10min'"
        ).fetchone()[0]
        trajectories = conn.execute(
            "SELECT COUNT(*) FROM trajectories WHERE bucket_size='10min'"
        ).fetchone()[0]
    assert windows == 6
    assert vectors == 6
    assert trajectories >= 1


def test_backfill_dry_run_does_not_write(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    _insert_logs(db_path, "billing-service", ["2026-06-16T10:00:00"])

    with sqlite3.connect(db_path) as conn:
        summary = backfill_ten_minute_metrics(conn, dry_run=True)

    assert summary["dry_run"] is True
    assert summary["total_events"] == 1
    # No rows are written on a dry run.
    assert _metric_counts(db_path, "10min") == 0


def test_backfill_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    stamps = [f"2026-06-16T10:{minute:02d}:00" for minute in range(0, 60, 10)]
    _insert_logs(db_path, "billing-service", stamps)

    with sqlite3.connect(db_path) as conn:
        backfill_ten_minute_metrics(conn)
    first = _metric_counts(db_path, "10min")
    with sqlite3.connect(db_path) as conn:
        backfill_ten_minute_metrics(conn)
    second = _metric_counts(db_path, "10min")

    assert first == 6
    assert second == 6  # rerun does not double count


def test_backfill_preserves_existing_buckets(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    stamps = [f"2026-06-16T10:{minute:02d}:00" for minute in range(0, 60, 10)]
    _insert_logs(db_path, "billing-service", stamps)

    # Establish 30min/hour/day metrics via the normal pipeline.
    run_detection_pipeline("billing-service")
    before = {
        bucket: _metric_counts(db_path, bucket) for bucket in ("30min", "hour", "day")
    }

    with sqlite3.connect(db_path) as conn:
        backfill_ten_minute_metrics(conn)

    after = {
        bucket: _metric_counts(db_path, bucket) for bucket in ("30min", "hour", "day")
    }
    assert before == after
    assert all(count > 0 for count in before.values())


def test_backfill_respects_service_filter(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    _insert_logs(db_path, "billing-service", ["2026-06-16T10:00:00"])
    _insert_logs(db_path, "auth-service", ["2026-06-16T10:00:00"])

    with sqlite3.connect(db_path) as conn:
        summary = backfill_ten_minute_metrics(conn, service_name="billing-service")
        rows = conn.execute(
            "SELECT DISTINCT service_name FROM pattern_time_series_metrics "
            "WHERE bucket_size='10min'"
        ).fetchall()

    assert summary["total_events"] == 1
    assert [r[0] for r in rows] == ["billing-service"]
