# AGENTS.md

이 문서는 저장소 전체에 적용되는 Codex 및 AI 에이전트 작업 지침이다. 하위 디렉터리에 별도의 `AGENTS.md`가 있으면 해당 파일의 지침이 더 우선한다.

## 1. 프로젝트 개요

LogDetect는 서비스 로그를 수집·정규화하고, 패턴과 이상 징후를 탐지하며, 근거 기반 대응 방안을 제공하는 AIOps 프로토타입이다. 저장소는 다음 세 애플리케이션으로 구성된다.

- `LOG_DETECT_AGENTS_BACK`: Python 3.11+, FastAPI, LangGraph 기반 백엔드
- `LOG_DETECT_AGENT_FRONT`: Vue 3, TypeScript, Vite 기반 기본 대시보드
- `LOG_DETECT_AGENT_STREAMLIT`: Python, Streamlit 기반 보조 대시보드
- `docs`: 설계, 시나리오, 실험 및 인수인계 문서

프론트엔드는 백엔드의 `/health`, `/services`, `/analyze`, `/analyze/stream` 및 PatternOps/추천 관련 API를 사용한다. API 계약을 변경할 때는 두 프론트엔드와 관련 테스트 및 문서를 함께 확인한다.

## 2. 현재 아키텍처

### 백엔드 처리 흐름

주 분석 그래프는 `app/graph/engine.py`의 `SharedState` 기반 LangGraph이다.

1. `OrchestratorAgent`가 PatternOps skill plan에 따라 다음 작업자를 선택한다.
2. `LogCollectorAgent`가 SQLite에서 분석 대상 로그를 수집한다.
3. `LogAnalysisAgent`가 로그 정규화, fingerprint 생성, 알려진 패턴 매칭 및 신규/중복 패턴 후보 생성을 수행한다.
4. `AnomalyDetectionAgent`가 패턴의 증가·감소·부재·신규 출현을 판정한다.
5. 각 노드는 실패 시 한 번 재시도하며, 최종 실패는 shared state에 기록하고 가능한 범위에서 처리를 계속한다.

추천 생성, Knowledge Card RAG, 승인/예외/정상 패턴 관리, PatternOps contract/skill 실행은 FastAPI 서비스 흐름에서 별도로 결합된다. `app/graph/builder.py`의 `/agents/run`용 단순 그래프와 주 `/analyze` 그래프를 혼동하지 않는다.

### 저장소

- SQLite: 현재 로그, 분석 결과, fingerprint, 추천 이력, Knowledge Card, PatternOps 데이터의 구조화 저장소
- ChromaDB: 패턴 cluster와 분석/Knowledge Card의 벡터 검색 저장소
- PostgreSQL: 목표 또는 호환 설정으로 남아 있으나 현재 런타임의 주 저장소가 아니다. 명시적 요청 없이 PostgreSQL 전환이나 스키마 변경을 하지 않는다.

## 3. 개발 환경 및 실행

기본 지원 환경은 Windows 10/11, Python 3.11+, pip, Node.js/npm이다. 명령은 각 프로젝트 디렉터리에서 실행한다.

### 백엔드

```powershell
cd LOG_DETECT_AGENTS_BACK
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -r requirements-dev.txt
Copy-Item .env.example .env.dev
python test_data_gen.py
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

macOS/Linux에서는 가상환경 활성화에 `source .venv/bin/activate`를 사용한다.

### Vue 프론트엔드

```powershell
cd LOG_DETECT_AGENT_FRONT
npm install
npm run dev
```

기본 백엔드 주소는 `http://localhost:8000`, Vite 개발 서버는 `http://localhost:5173`이다.

### Streamlit 프론트엔드

```powershell
cd LOG_DETECT_AGENT_STREAMLIT
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## 4. 환경 변수

백엔드는 `LOG_DETECT_AGENTS_BACK/.env.dev`를 읽는다. 실제 값이나 시크릿은 커밋하지 않고 `.env.example`에는 예시 또는 빈 값만 둔다.

### 로컬 실행 핵심 설정

- `SQLITE_PATH`: SQLite 파일 경로. 로컬 분석과 테스트 데이터 생성에 필요
- `CHROMADB_PATH`: ChromaDB 영속 경로, 기본값 `./.chroma`
- `LOG_LEVEL`: 애플리케이션 로그 레벨, 기본값 `INFO`
- `LLM_STUB_MODE`: 기본값은 `true`; 실제 LLM 호출은 명시적으로 `false`로 설정

### LLM 설정

- `OPENAI_API_KEY`
- `OPENAI_MODEL`, 기본값 `gpt-4o-mini`
- `OPENAI_BASE_URL`, 선택 사항

### 임베딩 설정

- `EMBEDDING_PROVIDER`: `openai` 또는 `azure_openai`
- OpenAI: `OPENAI_EMBEDDING_API_KEY`, `OPENAI_EMBEDDING_MODEL`, 선택적으로 `OPENAI_EMBEDDING_BASE_URL`
- Azure OpenAI: `AZURE_OPENAI_EMBEDDING_API_KEY`, `AZURE_OPENAI_EMBEDDING_ENDPOINT`, `AZURE_OPENAI_EMBEDDING_API_VERSION`, `AZURE_OPENAI_EMBEDDING_DEPLOYMENT`
- 튜닝: `OPENAI_EMBEDDING_DIMENSIONS`, `OPENAI_PATTERN_EMBEDDING_DIMENSIONS`, `OPENAI_CASE_CARD_EMBEDDING_DIMENSIONS`, `OPENAI_EMBEDDING_BATCH_SIZE`

일반 텍스트 생성용 키와 임베딩용 키를 동일하다고 가정하지 않는다. 외부 호출이 필요 없는 개발과 테스트에서는 stub 또는 테스트 대역을 우선 사용한다.

### 선택적 관측성 설정

- `LANGSMITH_TRACING`
- `LANGSMITH_API_KEY`
- `LANGSMITH_PROJECT`
- `LANGSMITH_ENDPOINT`

### 프론트엔드 설정

- Vue: `VITE_API_BASE_URL`, `VITE_ANALYZE_SSE_URL`
- Streamlit: `API_BASE_URL`

## 5. 변경 원칙

- 요구사항과 직접 관련된 최소 범위만 변경하고 사용자의 기존 변경을 보존한다.
- 백엔드 API 또는 `SharedState`를 변경하면 Pydantic schema, Vue 타입/store/API client, Streamlit API client 및 관련 테스트를 함께 점검한다.
- 로그 분석의 핵심 판정은 가능한 한 결정적이고 테스트 가능하게 유지한다. LLM 응답은 근거 데이터와 분리하고 실패 시 graceful degradation 경로를 보존한다.
- fingerprint, 정규화 규칙, suppression, accepted-normal, PatternOps contract의 변경은 기존 데이터 호환성과 탐지 결과 변화를 테스트한다.
- DB 접근은 `app/db`, MCP 연동은 `app/mcp`, 그래프 흐름은 `app/graph`, 에이전트 행위는 `app/agents`의 기존 경계를 따른다.
- Python은 Ruff 설정(줄 길이 100, Python 3.11)을 따르고 공개 함수와 복잡한 로직에는 타입과 간결한 docstring을 유지한다.
- TypeScript에서는 기존 타입을 우회하는 `any` 사용을 피하고 API 응답 타입과 UI 상태를 동기화한다.
- 생성 데이터, SQLite DB, ChromaDB 파일, `.env.dev`, `node_modules`, 빌드 산출물은 커밋하지 않는다.

## 6. 검증

변경 영역에 맞는 최소 검증을 실행하고, 완료 보고에 실행한 명령과 결과를 남긴다.

### 백엔드

```powershell
cd LOG_DETECT_AGENTS_BACK
python -m pytest
python -m ruff check app tests
```

필요하면 특정 테스트부터 실행한다.

```powershell
python -m pytest tests/test_health.py -q
```

### Vue 프론트엔드

```powershell
cd LOG_DETECT_AGENT_FRONT
npm run build
npm run lint
```

### Streamlit 프론트엔드

별도 자동화 테스트가 없으므로 변경 시 최소한 import/compile 검사와 백엔드 연동 화면을 확인한다.

```powershell
cd LOG_DETECT_AGENT_STREAMLIT
python -m compileall app.py api_client.py
```

테스트가 환경 변수, 외부 API, 기존 로컬 데이터 때문에 실행되지 않으면 실패 원인과 미검증 범위를 명확히 기록한다.

## 7. 안전 및 금지 사항

- 인프라, 배포 환경, DB 스키마를 임의로 변경하지 않는다.
- 시크릿, 인증 정보, 실제 로그의 개인정보를 출력·커밋·회전하지 않는다.
- `clear_table_data.py`, `clear_vector_data.py` 또는 데이터 삭제 명령은 사용자의 명시적 요청과 대상 확인 없이 실행하지 않는다.
- 운영 서비스 호출, 대량 외부 LLM/embedding 호출, 파괴적 Git 명령을 임의로 실행하지 않는다.
- 기존 DB나 ChromaDB를 테스트 fixture로 사용하지 않는다. 테스트는 임시 경로와 격리된 데이터를 사용한다.
- 장애 분석 결과를 확정적 사실로 과장하지 말고, 관측 근거·가정·신뢰도·추가 확인 항목을 함께 유지한다.

## 8. 작업 완료 기준

작업은 요청된 코드와 문서가 일치하고, 영향 범위에 맞는 검증이 통과하며, 시크릿이나 생성 산출물이 변경 목록에 포함되지 않았을 때 완료된다. 변경 전후 `git status`를 확인하고 사용자 소유의 관련 없는 수정은 건드리지 않는다.
