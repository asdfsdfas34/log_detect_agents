"""Generate the SQLite schema and deterministic demo data for SC-001~SC-007."""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from app.db.scenario_store import ensure_schema, fingerprint_id, run_detection_pipeline
from app.db.sqlite_store import _resolve_db_path

SERVICES = ["board-service", "login-service", "batch-service"]
KNOWN_SUBCATEGORIES = {
    "NullReference": ("개체 참조가 개체의 인스턴스로 설정되지 않았습니다.", "System.NullReferenceException at BoardService.GetPost({n})"),
    "IndexOutOfRange": ("Index was outside the bounds of the array.", "System.IndexOutOfRangeException at BoardService.List({n})"),
    "SqlException": ("SQL 실행 중 오류가 발생했습니다.", "System.Data.SqlClient.SqlException at LoginRepository.FindUser({n})"),
}
NEW_SUBCATEGORIES = {
    "TimeoutException": ("HTTP Timeout while calling payment gateway", "System.TimeoutException at HttpClient.Send({n})"),
    "IOException": ("I/O 오류로 파일을 읽을 수 없습니다.", "System.IOException at BatchFileReader.Read({n})"),
}


def main() -> None:
    """Recreate demo data with about 800 logs, known/new patterns, anomalies, and critical risks."""
    random.seed(42)
    db_path = Path(_resolve_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        ensure_schema(conn)
        cur = conn.cursor()
        cur.executescript(
            """
            DELETE FROM service_logs;
            DELETE FROM fingerprints;
            DELETE FROM known_patterns;
            DELETE FROM log_analysis_results;
            DELETE FROM anomaly_results;
            DELETE FROM impact_evaluations;
            DELETE FROM exception_registry;
            DELETE FROM knowledge_cards;
            """
        )
        now = datetime.utcnow()
        rows = []
        for i in range(800):
            service = random.choice(SERVICES)
            created_at = (now - timedelta(minutes=random.randint(0, 1440))).isoformat(timespec="seconds")
            bucket = random.random()
            if bucket < 0.45:
                level, message, stack = "INFO", "Request completed successfully", f"{service}.Health.Check({i})"
            elif bucket < 0.60:
                level, message, stack = "WARN", "CPU usage is above threshold", f"ResourceMonitor.Cpu.Sample({i})"
            elif bucket < 0.84:
                level = "ERROR"
                message, stack_t = random.choice(list(KNOWN_SUBCATEGORIES.values()))
                stack = stack_t.format(n=random.randint(1, 999))
            else:
                level = "ERROR"
                message, stack_t = random.choice(list(NEW_SUBCATEGORIES.values()))
                stack = stack_t.format(n=random.randint(1, 999))
            rows.append((service, level, message, stack, created_at))
        # Add concentrated recent spikes so at least five anomaly results and three critical risks exist.
        for n in range(60):
            rows.append(("login-service", "ERROR", "SQL 실행 중 오류가 발생했습니다.", f"System.Data.SqlClient.SqlException at LoginRepository.FindUser({n})", now.isoformat(timespec="seconds")))
        for n in range(45):
            rows.append(("board-service", "ERROR", "개체 참조가 개체의 인스턴스로 설정되지 않았습니다.", f"System.NullReferenceException at BoardService.GetPost({n})", now.isoformat(timespec="seconds")))
        for n in range(35):
            rows.append(("batch-service", "ERROR", "I/O 오류로 파일을 읽을 수 없습니다.", f"System.IOException at BatchFileReader.Read({n})", now.isoformat(timespec="seconds")))
        cur.executemany("INSERT INTO service_logs(service_name,level,message,stack_trace,created_at) VALUES (?,?,?,?,?)", rows)
        # Register known pattern rules by sub-category; about 60% of generated error families are known.
        for sub, (message, stack_t) in KNOWN_SUBCATEGORIES.items():
            cur.execute(
                "INSERT INTO known_patterns(fingerprint,category,sub_category,cause,recommendation,confidence) VALUES (?,?,?,?,?,?)",
                (None, "Exception", sub, f"{sub} known cause", f"{sub} 표준 조치 절차를 수행", "HIGH"),
            )
        conn.commit()
    result = run_detection_pipeline(None)
    print(f"Created {len(rows)} logs in {db_path}")
    print(f"Fingerprints: {result['summary']['total_fingerprints']}, anomalies: {result['summary']['anomalies_detected']}, risk: {result['summary']['risk_level']}")


if __name__ == "__main__":
    main()
