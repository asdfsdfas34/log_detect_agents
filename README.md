# LangGraph Multi-Agent FastAPI Starter (Windows + pip)

This project provides a FastAPI backend for a LangGraph-based multi-agent system using the OpenAI API.

## Quickstart (Windows PowerShell)

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

Create `.env` (copy from `.env.example`) and set required variables:
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `POSTGRESQL_URL`
- `CHROMADB_PATH`
- `LOG_LEVEL`

Run:

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open docs:
- http://127.0.0.1:8000/docs

## Endpoints
- `GET /health`
- `POST /agents/run`

## Agent Flow
`Log Collector -> Log Analysis -> Impact Evaluation -> Source Code Analysis -> Recommendation`

## Notes
- PostgreSQL is used for structured log retrieval.
- ChromaDB is used for vectorized incident history lookup.
- The system avoids infra changes, DB schema changes, secret rotation, and destructive commands.
