### Agent 페르소나 및 시스템 프롬프트 (Identity)

|              | 정의 내용                                                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------ |
| **Agent 이름** | Mini AIOps                                                                                                               |
| **주요 역할**    | 서비스 로그를 수집, 정규화, fingerprint화하고 Known/New 패턴 및 이상 징후를 탐지한 뒤, 유사 사례와 Knowledge Card를 참고해 장애 원인/영향/조치 방향을 제안하는 멀티 에이전트 시스템 |
| **핵심 목표**    | 장애 가능성을 조기에 탐지하고, 근거 기반의 안전한 수정 방향과 재발 방지 방안을 제시                                                                         |
| **톤앤매너**     | SRE/백엔드 엔지니어에게 보고하듯 간결하고 근거 중심적으로 답변. 한국어 사용자 응답을 기본으로 하며, 불확실한 부분은 추정하지 않고 추가 필요 데이터를 명시                                |
| **제약 사항**    | 인프라 변경, 임의 DB 스키마 변경, 시크릿/인증 정보 회전, 파괴적 운영 명령, 근거 없는 원인 단정 금지. 증거가 부족하면 `additional_data_needed`로 분리                     |

### 워크플로우 및 오케스트레이션 (Workflow & Logic)

**2.1 처리 로직**

* **Step 1 (Input Analysis):**

  * `/analyze` 요청의 `service_name`, `goal`, `analysis_date`, `scope`, `save_to_chromadb`를 기반으로 `SharedState`를 초기화한다.

  * 분석 범위는 서비스명, 날짜 범위, filters로 구성되며 이후 Agent/Skill 실행의 공통 컨텍스트로 사용된다.

* **Step 2 (Skill Selection & Orchestration):**

  * LangGraph의 `OrchestratorAgent`는 상위 실행 순서를 관리하지만, 실제 세부 작업은 각 Agent가 `pattern_skill_runner.run_for_agent(...)`를 통해 현재 scope에 맞는 PatternOps/SkillOps skill을 선택하고 실행한다.

  * 예를 들어 `LogAnalysisAgent`는 `log_normalization`, `pattern_fingerprint`, `known_pattern_match` skill을, `RecommendationAgent`는 `knowledge_card_retrieval`, `recommendation_generation`, `recommendation_quality_gate` skill을 수행한다.

* **Step 3 (Execution & Response):**

  * 실행된 skill의 산출물은 `SharedState.evidence`, `assessment`, `decisions`, `rag`, `final`에 누적된다.

  * 이후 deterministic scenario pipeline, PatternOps skill plan, ChromaDB RAG 조회 결과를 통합하여 `AnalyzeResponse`를 생성한다.

  * 선택된 fingerprint에 대한 최종 권고는 `/recommendations/fingerprint`에서 Recommendation skill chain을 통해 별도 생성된다.

**2.2 상태 관리**

**대화 턴(Turn) 관리를 위한 상태 정의**

* 현재 시스템은 요청 단위의 공유 상태인 `SharedState`를 중심으로 동작한다. 각 Agent와 `pattern_skill_runner`는 동일한 상태를 읽고 갱신하며, 분석 결과와 실행 이력은 공통 상태에 누적된다.

| 상태 영역           | 관리 내용                                                               |
| --------------- | ------------------------------------------------------------------- |
| `scope`         | 분석 대상 서비스, 기간, 필터                                                   |
| `evidence`      | 로그, fingerprint, known/new pattern, anomaly, cluster, PatternOps 결과 |
| `assessment`    | risk score, confidence, 판단 근거                                       |
| `decisions`     | 실행/스킵된 Agent, assumptions, failures                                 |
| `orchestration` | 다음 실행 대상, pending/completed Agent                                   |
| `rag`           | ChromaDB 기반 유사 사례 및 지식 조회 결과                                        |
| `final`         | 최종 응답, 권고 조치, 검증 단계, evidence bundle                                |

* 대화형 장기 메모리보다는 요청 단위 상태 관리가 중심이며, 승인된 결과나 최종 답변은 Knowledge Card 또는 ChromaDB를 통해 장기 지식으로 저장된다.

**LangGraph Node/Edge 흐름 기술**

* LangGraph는 상위 실행 흐름을 관리하고, 각 Agent 내부의 세부 처리는 `pattern_skill_runner`를 통해 skill 단위로 수행된다.

```text
START
→ OrchestratorAgent
→ LogCollectorAgent
→ OrchestratorAgent
→ LogAnalysisAgent
→ OrchestratorAgent
→ AnomalyDetectionAgent
→ OrchestratorAgent
→ END
```

* `OrchestratorAgent`는 `orchestration.completed_agents`를 기준으로 다음 실행 대상을 결정한다.

* 실행된 Agent와 실패/스킵 정보는 `decisions`에 기록되며, 실행된 skill 계획과 이력은 `evidence.pattern_ops_skill_plan`, `evidence.pattern_ops_skill_executions`, `evidence.pattern_ops_validator_results`에 저장된다.

* 기본 `/analyze` 흐름은 분석 근거와 위험도 중심 결과를 반환하고, 선택된 fingerprint에 대한 상세 권고는 `/recommendations/fingerprint`에서 `RecommendationAgent`와 관련 skill chain을 통해 별도로 생성된다.

### 도구(Tools) 및 함수 명세 (Capability)

| 도구명 (Function Name)                  | 기능 설명 (Description)                                                   | 입력 파라미터 (Input Schema)                                | 출력 데이터 (Output)                                             |
| ------------------------------------ | --------------------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------- |
| `sqlite.fetch_recent_log_entries`    | 서비스별 최근 구조화 로그 조회                                                     | `service_names: list[str]`, `limit: int`              | `[{system, level, message, timestamp, stack_trace}]`        |
| `sqlite.save_log_analysis`           | 로그 분석 결과 저장                                                           | `goal: str`, `service_name: str`, `analysis: str`     | `None`                                                      |
| `chromadb.find_related_analyses`     | ChromaDB에서 유사 분석/Knowledge Card 조회                                    | `query: str`, `n_results: int`                        | `list[str]`                                                 |
| `chromadb.save_analysis_document`    | 최종 답변 또는 지식 문서 저장                                                     | `doc_id: str`, `text: str`, `metadata: dict`          | `bool`                                                      |
| `openai.generate_text`               | OpenAI Responses API 기반 텍스트/JSON 생성                                   | `messages: list`, `model?: str`, `temperature: float` | `str`                                                       |
| `msgraph.request`                    | Microsoft Graph API 요청 래퍼                                             | `endpoint, method, token, params, body, timeout_s`    | `dict`                                                      |
| `run_detection_pipeline`             | fingerprint, anomaly, risk, recommendation 후보 등 deterministic 시나리오 분석 | `service_name: str`, `analysis_date: str`             | `summary`, `fingerprints`, `anomalies`, `recommendations` 등 |
| `PatternRuleSuggestionAgent.propose` | 로그 메시지 기반 정규화 regex/template 제안                                       | `cluster: str`, `message: str`                        | `{name, match_regex, template, confidence, reason}`         |

### 지식 베이스 및 메모리 전략 (Context & Memory)

아래는 현재 코드 기준으로 정리한 문안입니다. 기준 파일은 [engine.py](/Users/a10068/Desktop/log_detect_agents/LOG_DETECT_AGENTS_BACK/app/graph/engine.py:15), [state.py](/Users/a10068/Desktop/log_detect_agents/LOG_DETECT_AGENTS_BACK/app/state.py:81), [main.py](/Users/a10068/Desktop/log_detect_agents/LOG_DETECT_AGENTS_BACK/app/main.py:541), [mcp/server.py](/Users/a10068/Desktop/log_detect_agents/LOG_DETECT_AGENTS_BACK/app/mcp/server.py:24), [recommendation.py](/Users/a10068/Desktop/log_detect_agents/LOG_DETECT_AGENTS_BACK/app/agents/recommendation.py:18), [chroma_store.py](/Users/a10068/Desktop/log_detect_agents/LOG_DETECT_AGENTS_BACK/app/db/chroma_store.py:16)입니다.

### Agent 페르소나 및 시스템 프롬프트 (Identity)

|              | 정의 내용                                                                                                                    |
| ------------ | ------------------------------------------------------------------------------------------------------------------------ |
| **Agent 이름** | Failure Prevention AIOps Agent                                                                                           |
| **주요 역할**    | 서비스 로그를 수집, 정규화, fingerprint화하고 Known/New 패턴 및 이상 징후를 탐지한 뒤, 유사 사례와 Knowledge Card를 참고해 장애 원인/영향/조치 방향을 제안하는 멀티 에이전트 시스템 |
| **핵심 목표**    | 장애 가능성을 조기에 탐지하고, 근거 기반의 안전한 수정 방향과 재발 방지 방안을 제시                                                                         |
| **톤앤매너**     | SRE/백엔드 엔지니어에게 보고하듯 간결하고 근거 중심적으로 답변. 한국어 사용자 응답을 기본으로 하며, 불확실한 부분은 추정하지 않고 추가 필요 데이터를 명시                                |
| **제약 사항**    | 인프라 변경, 임의 DB 스키마 변경, 시크릿/인증 정보 회전, 파괴적 운영 명령, 근거 없는 원인 단정 금지. 증거가 부족하면 `additional_data_needed`로 분리                     |

### 워크플로우 및 오케스트레이션 (Workflow & Logic)

**2.1 처리 로직**

* **Step 1 (Input Analysis):** `/analyze` 요청의 `service_name`, `goal`, `analysis_date`, `scope`, `save_to_chromadb`를 받아 `SharedState`를 초기화합니다. 분석 범위는 서비스명과 날짜 범위 중심으로 고정됩니다.

* **Step 2 (Tool Selection):** `OrchestratorAgent`가 순서 기반으로 `LogCollectorAgent → LogAnalysisAgent → AnomalyDetectionAgent`를 선택합니다. 이후 API 레이어에서 deterministic scenario pipeline, PatternOps skill plan, RAG 조회를 추가 실행합니다. 선택 fingerprint 권고는 `/recommendations/fingerprint`에서 `RecommendationAgent`가 별도로 수행합니다.

* **Step 3 (Execution & Response):** 로그/패턴/이상탐지/위험도/유사 지식/PatternOps 결과를 `evidence_bundle`로 통합하고 `AnalyzeResponse.result`로 반환합니다. 권고 생성 시에는 LLM JSON 결과를 파싱하고 quality gate를 통과하거나 best-effort/fallback 결과를 반환합니다.

**2.2 상태 관리**

* 상태는 `SharedState` 단일 객체로 관리합니다: `goal`, `request_id`, `scope`, `evidence`, `metrics`, `assessment`, `decisions`, `final`, `orchestration`, `preferences`, `rag`.

* LangGraph 흐름: `START → orchestrator → log_collector → orchestrator → log_analysis → orchestrator → anomaly_detection → orchestrator → END`.

* `/analyze` 기본 흐름에서는 `RecommendationAgent`가 명시적으로 skipped 처리됩니다. 실제 권고문 생성은 사용자가 특정 fingerprint를 선택한 뒤 `/recommendations/fingerprint`에서 실행됩니다.

### 도구(Tools) 및 함수 명세 (Capability)

| 도구명 (Function Name)                  | 기능 설명 (Description)                                                   | 입력 파라미터 (Input Schema)                                | 출력 데이터 (Output)                                             |
| ------------------------------------ | --------------------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------- |
| `sqlite.fetch_recent_log_entries`    | 서비스별 최근 구조화 로그 조회                                                     | `service_names: list[str]`, `limit: int`              | `[{system, level, message, timestamp, stack_trace}]`        |
| `sqlite.save_log_analysis`           | 로그 분석 결과 저장                                                           | `goal: str`, `service_name: str`, `analysis: str`     | `None`                                                      |
| `chromadb.find_related_analyses`     | ChromaDB에서 유사 분석/Knowledge Card 조회                                    | `query: str`, `n_results: int`                        | `list[str]`                                                 |
| `chromadb.save_analysis_document`    | 최종 답변 또는 지식 문서 저장                                                     | `doc_id: str`, `text: str`, `metadata: dict`          | `bool`                                                      |
| `openai.generate_text`               | OpenAI Responses API 기반 텍스트/JSON 생성                                   | `messages: list`, `model?: str`, `temperature: float` | `str`                                                       |
| `run_detection_pipeline`             | fingerprint, anomaly, risk, recommendation 후보 등 deterministic 시나리오 분석 | `service_name: str`, `analysis_date: str`             | `summary`, `fingerprints`, `anomalies`, `recommendations` 등 |
| `PatternRuleSuggestionAgent.propose` | 로그 메시지 기반 정규화 regex/template 제안                                       | `cluster: str`, `message: str`                        | `{name, match_regex, template, confidence, reason}`         |

### 지식 베이스 및 메모리 전략 (Context & Memory)

**4.1 RAG (검색 증강 생성) 전략**

* **참조 데이터 소스:** SQLite 기반 `service_logs`, `known_patterns`, `knowledge_cards`, recommendation history, PatternOps contracts, ChromaDB collections.

* **청킹(Chunking) 방식:** Pattern cluster는 service/fingerprint/level/status/normalized message/context 섹션으로 구성하고, Knowledge Card/incident summary는 문서 단위로 저장합니다.

* **임베딩 모델:** 기본 `text-embedding-3-large`. Pattern template은 기본 1024차원, Case Card/Incident Summary는 기본 1536차원.

* **Vector DB:** ChromaDB PersistentClient. 주요 collection은 `pattern_templates_v2`, `case_cards_v2`, `known_patterns_v2`, `incident_summaries_v2`, legacy `incident_analyses`.

**4.2 대화 메모리 (Conversation History)**

* **메모리 유형:** `/analyze`는 장기 대화형 메모리보다 request-scoped `SharedState` 중심입니다. 장기 지식은 Knowledge Card, recommendation history, ChromaDB 문서로 저장됩니다.

* **저장 전략:** 요청 단위 상태는 응답 후 종료됩니다. 승인된 조치 결과는 `/approvals`를 통해 Knowledge Card로 저장하고, 최종 답변은 `save_to_chromadb=true`일 때 ChromaDB에 저장됩니다. 에이전트 실행 로그는 LangSmith 또는 로컬 200개 이벤트 버퍼로 추적합니다.

### 핵심 에이전트 기술 스택

| 구분                         | 선정 전략/기술                                                                 | 선정 사유 (논리적 근거)                                       |
| -------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------- |
| **LLM Model**              | 기본 `gpt-4.1-mini`, `OPENAI_MODEL`로 교체 가능                                 | 비용/속도 균형이 좋고 한국어 권고 생성에 충분. 고난도 RCA에는 상위 모델로 교체 가능   |
| **Agent Framework**        | LangGraph `StateGraph`                                                   | 순차 오케스트레이션, 상태 공유, 노드 재시도/실패 기록이 명확함                 |
| **Prompt Strategy**        | Deterministic-first + Evidence-grounded structured prompt + quality gate | 로그 정규화/탐지는 규칙 기반으로 안정화하고, LLM은 권고 생성과 평가에 집중         |
| **Output Parsing**         | JSON object 강제, 커스텀 파서/검증, quality score 80점 기준                          | 권고 조치, 검증 단계, 예방 단계처럼 UI와 저장소가 요구하는 정형 필드를 안정적으로 확보  |
| **Monitoring**             | LangSmith + local agent-flow event buffer                                |                                                      |
| **RAG / Memory**           | ChromaDB + Knowledge Card + PatternOps Registry                          | 유사 장애 사례와 승인된 해결책을 재사용하고 fingerprint/패턴 기반 검색 품질을 높임 |
| **Operational Guardrails** | 금지 제안 hard-fail check                                                    | 인프라 변경, DB 스키마 변경, 시크릿 회전, 파괴 명령 같은 위험한 권고를 차단       |
