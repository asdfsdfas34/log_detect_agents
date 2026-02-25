# LangGraph Multi-Agent FastAPI Starter (Windows + pip)

This project provides a FastAPI backend for a LangGraph-style multi-agent system for failure-prevention analysis.

## Quickstart (Windows PowerShell)

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Create `.env` and set required variables:
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `SQLITE_PATH` (권장)
- `POSTGRESQL_URL` (레거시 호환용, 없으면 무시)
- `CHROMADB_PATH`
- `LOG_LEVEL`

## Run server

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open docs:
- http://127.0.0.1:8000/docs

## Endpoints
- `GET /health`
- `POST /analyze`

## SQLite sample data setup (optional)

```powershell
python -c "import sqlite3; conn=sqlite3.connect('data/logs.db'); cur=conn.cursor(); cur.execute('CREATE TABLE IF NOT EXISTS service_logs (service_name TEXT, message TEXT, created_at TEXT)'); cur.execute(\"INSERT INTO service_logs(service_name, message, created_at) VALUES (?, ?, ?)\", ('checkout-api', 'ERROR timeout while calling payment provider', '2026-02-18T09:40:01')); cur.execute(\"INSERT INTO service_logs(service_name, message, created_at) VALUES (?, ?, ?)\", ('checkout-api', 'WARN retry attempt=1', '2026-02-18T09:40:03')); conn.commit(); conn.close()"
$env:SQLITE_PATH = "data/logs.db"
```

## Sample-data test (Windows PowerShell)

1) 서버 실행 후, 샘플 요청 파일(`samples/run_request.json`)로 테스트:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8000/analyze" `
  -ContentType "application/json" `
  -InFile "samples/run_request.json"
```

2) 또는 curl 사용:

```powershell
curl -X POST "http://127.0.0.1:8000/analyze" ^
  -H "Content-Type: application/json" ^
  --data-binary "@samples/run_request.json"
```

3) 테스트 코드로 검증:

```powershell
pytest -q
```

## Agent Flow
`collect_logs -> analyze_logs -> evaluate_impact -> (optional source_code_analysis) -> recommend`

## Notes
- SQLite: structured data (local file)
- ChromaDB: vector embeddings
- Out of scope: infra changes, DB schema changes, secret rotation, destructive operations

## Vue 3 Enterprise Dashboard (LogDetect)

A Vue 3 + TypeScript + Vite dashboard is included in this repository and integrates with the backend API contracts:

- `GET /health`
- `POST /analyze`

SSE is not currently exposed by the backend, so the frontend automatically uses a 5-second polling fallback for health updates during execution.

### Frontend run

```bash
npm install
npm run dev
```

Optional env vars:

- `VITE_API_BASE_URL` (default: `http://localhost:8000`)
- `VITE_ANALYZE_SSE_URL` (optional SSE endpoint if added later)
