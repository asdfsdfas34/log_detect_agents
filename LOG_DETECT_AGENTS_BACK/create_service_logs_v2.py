"""Create and populate service_logs_v2 from existing service_logs rows."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from app.db.scenario_store import populate_service_logs_v2
from app.db.sqlite_store import _resolve_db_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Populate service_logs_v2 from service_logs."
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing service_logs_v2 rows before inserting converted rows.",
    )
    args = parser.parse_args()

    db_path = Path(_resolve_db_path())
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        count = populate_service_logs_v2(conn, replace=args.replace)

    action = "Rebuilt" if args.replace else "Upserted"
    print(f"{action} {count} service_logs_v2 rows in {db_path}")


if __name__ == "__main__":
    main()
