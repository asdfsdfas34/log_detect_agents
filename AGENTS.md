# AGENTS.md
(Windows / pip / FastAPI / LangGraph / OpenAI)

---

## 1. Purpose

본 저장소는 **Python + LangGraph 기반 멀티 에이전트 시스템**을 구축하기 위한 프로젝트이다.  
시스템은 **FastAPI 기반 백엔드 서버**로 제공되며, **프론트엔드는 별도로 구성**된다.

주요 목적은 다음과 같다.

- 시스템/서비스 로그를 자동 수집 및 분석
- 장애 가능성 사전 탐지
- 소스 코드 영향 범위 분석
- 수정 방향 및 재발 방지 방안 자동 제안

❌ Out of Scope (금지 사항)
- 인프라 변경
- DB 스키마 임의 변경
- 시크릿/인증 정보 회전
- 파괴적 운영 명령 실행

---

## 2. Execution Environment

- OS: **Windows 10 / Windows 11**
- Python: **3.11+**
- Package Manager: **pip**
- API Framework: **FastAPI**
- LLM: **OpenAI API**
- Multi-Agent Framework: **LangGraph**

---

## 3. Windows Setup

### Virtual Environment
```powershell
py -m venv .venv
.venv\Scripts\activate
```

### Install Dependencies
```powershell
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

---

## 4. Environment Variables

Required variables (names only):

- OPENAI_API_KEY
- OPENAI_MODEL
- POSTGRESQL_URL
- CHROMADB_PATH
- LOG_LEVEL

---

## 5. Multi-Agent Architecture

### Agents
1. Log Collector Agent
2. Log Analysis Agent
3. Impact Evaluation Agent
4. Source Code Analysis Agent
5. Recommendation Agent

---

## 6. Databases

- PostgreSQL: structured data
- ChromaDB: vector embeddings

---

## Final Note
This document defines the top-level operational rules for Codex and AI agents.
