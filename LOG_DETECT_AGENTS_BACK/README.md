# LogDetect Monorepo

프로젝트 구조를 프론트엔드/백엔드로 완전히 분리했습니다.

## 디렉터리 구조

- `LOG_DETECT_AGENTS_BACK`: FastAPI + LangGraph 백엔드
- `LOG_DETECT_AGENT_FRONT`: Vue 3 + TypeScript 대시보드 프론트엔드

## Backend 실행

```bash
cd LOG_DETECT_AGENTS_BACK
pip install -r requirements.txt
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend 실행

```bash
cd LOG_DETECT_AGENT_FRONT
npm install
npm run dev
```
