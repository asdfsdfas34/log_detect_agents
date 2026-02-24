import sqlite3
from pathlib import Path

from app.db.sqlite_store import fetch_recent_logs


def test_fetch_recent_logs_from_sqlite(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "logs.db"
    monkeypatch.setenv("SQLITE_PATH", str(db_path))

    with sqlite3.connect(db_path) as conn:
        cur = conn.cursor()
        cur.execute(
            "CREATE TABLE service_logs (service_name TEXT, message TEXT, created_at TEXT)"
        )
        cur.execute(
            "INSERT INTO service_logs(service_name, message, created_at) VALUES (?, ?, ?)",
            ("checkout-api", "ERROR timeout", "2026-02-18T09:40:01"),
        )
        cur.execute(
            "INSERT INTO service_logs(service_name, message, created_at) VALUES (?, ?, ?)",
            ("checkout-api", "WARN retry", "2026-02-18T09:40:03"),
        )
        conn.commit()

    logs = fetch_recent_logs(service_name="checkout-api", limit=10)
    assert logs == ["WARN retry", "ERROR timeout"]

    # keep environment clean for other tests
    monkeypatch.delenv("SQLITE_PATH", raising=False)
    monkeypatch.delenv("POSTGRESQL_URL", raising=False)
