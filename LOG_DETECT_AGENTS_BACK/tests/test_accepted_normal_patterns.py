"""Tests for the accepted-normal feedback loop added alongside exception ignores.

Accepted normal differs from ``/exceptions`` ignores: the fingerprint stays
visible in the dashboard list and is only excluded from the anomaly count while
it remains inside the approved baseline. Exceeding the baseline re-detects it as
``ACCEPTED_NORMAL_BREACH``.
"""

import sqlite3
from pathlib import Path

from app.db.scenario_store import (
    ensure_schema,
    fetch_accepted_normal_patterns,
    fetch_exception_registry,
    register_accepted_normal_pattern,
    register_exception,
    revoke_accepted_normal_pattern,
    run_detection_pipeline,
)

MESSAGE = "Batch job failed for account balance sync"


def _seed(db_path: Path, date: str, count: int, *, minute0: int = 0) -> None:
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        conn.executemany(
            """
            INSERT INTO service_logs(service_name, level, message, stack_trace, created_at)
            VALUES ('batch-service', 'ERROR', ?, '', ?)
            """,
            [
                (MESSAGE, f"{date}T10:{(minute0 + index) % 60:02d}:00")
                for index in range(count)
            ],
        )
        conn.commit()


def _spiking_fingerprint(db_path: Path) -> str:
    """Seed a low daily baseline then a spike so the FP is a real SPIKE anomaly."""

    _seed(db_path, "2026-06-14", 2)
    _seed(db_path, "2026-06-15", 2)
    run_detection_pipeline("batch-service")
    _seed(db_path, "2026-06-16", 10)
    result = run_detection_pipeline("batch-service")
    fingerprint = result["fingerprints"][0]["fingerprint"]
    assert any(a["pattern"] == fingerprint for a in result["anomalies"]), (
        "test setup must produce a real anomaly before approval"
    )
    return fingerprint


def _row(result: dict, fingerprint: str) -> dict | None:
    for row in result["fingerprints"]:
        if row["fingerprint"] == fingerprint:
            return row
    return None


def test_accepted_normal_removes_fingerprint_from_anomalies(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    fingerprint = _spiking_fingerprint(db_path)

    register_accepted_normal_pattern(
        fingerprint=fingerprint,
        reason="Reviewed: expected batch noise",
        approved_by="operator",
    )

    rerun = run_detection_pipeline("batch-service")
    assert not any(a["pattern"] == fingerprint for a in rerun["anomalies"])
    assert rerun["summary"]["accepted_normal_count"] == 1
    assert rerun["summary"]["accepted_normal_breach_count"] == 0


def test_accepted_normal_stays_visible_with_status(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    fingerprint = _spiking_fingerprint(db_path)

    register_accepted_normal_pattern(
        fingerprint=fingerprint,
        reason="Reviewed: expected batch noise",
    )

    rerun = run_detection_pipeline("batch-service")
    row = _row(rerun, fingerprint)
    assert row is not None, "accepted normal fingerprint must stay visible"
    assert row["accepted_normal"] is True
    assert row["accepted_normal_status"] == "active"
    assert row["accepted_normal_reason"] == "Reviewed: expected batch noise"
    assert row["anomaly_type"] == "ACCEPTED_NORMAL"


def test_accepted_normal_breach_when_count_exceeds_allowed(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    fingerprint = _spiking_fingerprint(db_path)

    # Approve with a ceiling equal to the current occurrence count (14).
    register_accepted_normal_pattern(
        fingerprint=fingerprint,
        reason="Reviewed: expected batch noise",
        max_allowed_count=14,
    )
    normal = run_detection_pipeline("batch-service")
    assert _row(normal, fingerprint)["anomaly_type"] == "ACCEPTED_NORMAL"
    assert not any(a["pattern"] == fingerprint for a in normal["anomalies"])

    # Push the occurrence count above the ceiling.
    _seed(db_path, "2026-06-16", 6, minute0=20)
    breached = run_detection_pipeline("batch-service")
    row = _row(breached, fingerprint)
    assert row is not None
    assert row["accepted_normal"] is True
    assert row["anomaly_type"] == "ACCEPTED_NORMAL_BREACH"
    assert breached["summary"]["accepted_normal_breach_count"] == 1
    assert any(
        a["pattern"] == fingerprint and a["anomaly_type"] == "ACCEPTED_NORMAL_BREACH"
        for a in breached["anomalies"]
    )


def test_revoked_accepted_normal_no_longer_applies(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    fingerprint = _spiking_fingerprint(db_path)

    registered = register_accepted_normal_pattern(
        fingerprint=fingerprint,
        reason="Reviewed: expected batch noise",
    )
    suppressed = run_detection_pipeline("batch-service")
    assert not any(a["pattern"] == fingerprint for a in suppressed["anomalies"])

    revoke_result = revoke_accepted_normal_pattern(registered["id"])
    assert revoke_result["status"] == "revoked"

    rerun = run_detection_pipeline("batch-service")
    row = _row(rerun, fingerprint)
    assert row is not None
    assert row["accepted_normal"] is False
    assert any(a["pattern"] == fingerprint for a in rerun["anomalies"])
    assert rerun["summary"]["accepted_normal_count"] == 0

    patterns = fetch_accepted_normal_patterns(fingerprint=fingerprint)
    assert patterns[0]["status"] == "revoked"


def test_exception_registry_still_ignores_and_hides(
    tmp_path: Path, monkeypatch
) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))
    fingerprint = _spiking_fingerprint(db_path)

    register_exception(fingerprint, "known noisy batch failure")

    rerun = run_detection_pipeline("batch-service")
    # Exception behaviour is unchanged: hidden from the fingerprint list entirely.
    assert _row(rerun, fingerprint) is None
    assert not any(a["pattern"] == fingerprint for a in rerun["anomalies"])
    assert rerun["summary"]["exception_registered_count"] == 1
    assert fetch_exception_registry(fingerprint=fingerprint)[0]["reason"] == (
        "known noisy batch failure"
    )
