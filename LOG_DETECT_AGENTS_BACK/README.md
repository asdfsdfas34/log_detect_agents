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
source .venv/bin/activate
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## Frontend 실행

```bash
cd LOG_DETECT_AGENT_FRONT
npm install
npm run dev
```

## 로그 기반 장애 분석 시나리오 실행

이 백엔드는 SC-001~SC-007 흐름을 SQLite 기반 데모 데이터로 실행할 수 있습니다.

### ChromaDB OpenAI 임베딩 설정

ChromaDB v2 임베딩은 일반 LLM 호출용 `OPENAI_API_KEY`가 아니라 별도 키인
`OPENAI_EMBEDDING_API_KEY`를 사용합니다. 키가 없으면 기존 ChromaDB 저장/검색 경로는
유지되고, OpenAI 임베딩 기반 v2 collection 저장은 건너뜁니다.

```bash
OPENAI_EMBEDDING_API_KEY=...
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
OPENAI_PATTERN_EMBEDDING_DIMENSIONS=1024
OPENAI_CASE_CARD_EMBEDDING_DIMENSIONS=1536
```

Embedding provider can be selected with `EMBEDDING_PROVIDER`.

OpenAI:

```bash
EMBEDDING_PROVIDER=openai
OPENAI_EMBEDDING_API_KEY=...
OPENAI_EMBEDDING_MODEL=text-embedding-3-large
```

Azure OpenAI:

```bash
EMBEDDING_PROVIDER=azure_openai
AZURE_OPENAI_EMBEDDING_API_KEY=...
AZURE_OPENAI_EMBEDDING_ENDPOINT=https://<resource>.openai.azure.com
AZURE_OPENAI_EMBEDDING_API_VERSION=2024-02-01
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=<embedding-deployment-name>
```

### 테스트 데이터 생성

```bash
cd LOG_DETECT_AGENTS_BACK
python test_data_gen.py
```

`test_data_gen.py`는 최초 실행 시 필요한 테이블을 생성하고 약 800건 이상의 로그를 삽입합니다. 생성되는 테이블은 `service_logs`, `fingerprints`, `log_analysis_results`, `anomaly_results`, `impact_evaluations`, `exception_registry`, `knowledge_cards`, `known_patterns`입니다.

### API 실행

```bash
uvicorn app.main:app --reload
```

### 주요 API

- `POST /analyze`: 로그 수집, Fingerprint 생성, 패턴 분류, 이상 탐지, Risk Score 계산, 추천 결과를 반환합니다.
- `POST /exceptions`: Fingerprint Ignore 예외를 등록하고 이후 Risk/Anomaly 탐지에서 제외합니다.
- `POST /approvals`: 승인된 분석 결과를 Knowledge Card로 저장하고 이후 추천 검색에 사용합니다.
- `GET /services`: 테스트 데이터에 포함된 서비스 목록을 반환합니다.

### Dashboard 표시 항목

프론트엔드 대시보드는 계기판 대신 숫자형 Impact Score를 표시하며 Detection Summary, Risk Summary, Recommendation Summary를 표시합니다. Frequency, Time, Traffic 항목은 표시하지 않습니다.
