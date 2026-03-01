import sqlite3

conn = sqlite3.connect("./data/logs.db")
cursor = conn.cursor()

cursor.execute("SELECT * FROM service_logs")
rows = cursor.fetchall()

for row in rows:
    print(row)

conn.close()