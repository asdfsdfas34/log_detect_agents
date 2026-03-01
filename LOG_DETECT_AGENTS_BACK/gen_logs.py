import sqlite3
import random
from datetime import datetime, timedelta

conn = sqlite3.connect("logs.db")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS service_logs (
    service_name TEXT,
    level TEXT,
    message TEXT,
    created_at TEXT,
    stack_trace TEXT
)
""")

levels = ["DEBUG", "INFO", "ERROR"]
service_name = "logdetect-service"

for i in range(100):
    level = random.choice(levels)

    if level == "DEBUG":
        message = "Debug trace: step=%d, request_id=%d" % (
            random.randint(1,8),
            random.randint(100000,999999)
        )
        stack_trace = None

    elif level == "INFO":
        message = "Info: operation=health-check, duration=%dms" % (
            random.randint(10,5000)
        )
        stack_trace = None

    else:
        message = "Error: failed to connect DB, error_code=E%d" % (
            random.randint(100,999)
        )
        stack_trace = """Traceback (most recent call last):
  File "service.py", line %d, in handle
  File "repository.py", line %d, in query
Exception: Simulated failure""" % (
            random.randint(10,200),
            random.randint(10,200)
        )

    created_at = (datetime.now() - timedelta(
        minutes=random.randint(0, 4320)
    )).isoformat()

    cursor.execute("""
    INSERT INTO service_logs (service_name, level, message, created_at, stack_trace)
    VALUES (?, ?, ?, ?, ?)
    """, (service_name, level, message, created_at, stack_trace))

conn.commit()
conn.close()

print("100 logs inserted successfully.")