import sqlite3
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
import os


def get_db_path():
    """
    .env.dev 에서 SQLITE_PATH 읽기
    """
    
    project_root = Path(__file__).resolve().parent.parent.parent
    print(project_root)
    env_file = project_root / ".env.dev"

    load_dotenv(env_file)

    db_path = os.getenv("SQLITE_PATH")
    print(db_path)

    if not db_path:
        raise ValueError("SQLITE_PATH가 설정되어 있지 않습니다.")

    return db_path


def _resolve_db_path() -> str:
    """Resolve SQLite database path from environment variables."""

    project_root = Path(__file__).resolve().parent.parent.parent
    print(project_root)
    env_file = project_root / ".env.dev"

    load_dotenv(env_file)
    print(env_file)


    db_path = os.getenv("SQLITE_PATH")
    print(db_path)


    if not db_path:
        raise ValueError("SQLITE_PATH가 설정되어 있지 않습니다.")

    return db_path

def import_excel_to_sqlite(excel_file: str):
    """
    Excel → SQLite 저장
    """

    db_path = _resolve_db_path()
    if not db_path:
        return []

    query = (
        "SELECT DISTINCT service_name FROM service_logs "
        "WHERE COALESCE(TRIM(service_name), '') != '' "
        "ORDER BY service_name ASC "
        "LIMIT ?"
    )

    try:
        with sqlite3.connect(db_path) as conn:
            cur = conn.cursor()
            cur.execute(query, (100,))
            rows = cur.fetchall()
    except Exception:
        return []

    return [print(row) for row in rows]

    # df = pd.read_excel(excel_file)

    # required_columns = [
    #     "service_name",
    #     "level",
    #     "message",
    #     "created_at",
    #     "stack_trace",
    # ]

    # missing = [c for c in required_columns if c not in df.columns]

    # if missing:
    #     raise ValueError(
    #         f"엑셀에 필수 컬럼이 없습니다. 누락 컬럼: {missing}"
    #     )

    # with sqlite3.connect(db_path) as conn:

    #     cur = conn.cursor()

    #     insert_sql = """
    #     INSERT INTO service_logs
    #     (
    #         service_name,
    #         level,
    #         message,
    #         created_at,
    #         stack_trace
    #     )
    #     VALUES (?, ?, ?, ?, ?)
    #     """

    #     rows = [
    #         (
    #             str(row["service_name"]),
    #             str(row["level"]),
    #             str(row["message"]),
    #             str(row["created_at"]),
    #             str(row["stack_trace"])
    #         )
    #         for _, row in df.iterrows()
    #     ]

    #     cur.executemany(insert_sql, rows)

    #     conn.commit()

    # print(f"{len(rows)}건 저장 완료")


if __name__ == "__main__":

    import_excel_to_sqlite(
        "./lll.xlsx"
    )