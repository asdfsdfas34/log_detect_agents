### Agent 페르소나 및 시스템 프롬프트 (Identity)

| | 정의 내용 |
| ------------ | ------------- |
| **Agent 이름** | Failure Prevention AI Agent |
| **주요 역할** | 서비스 로그를 수집, 정규화, fingerprint화하고 Known/New Pattern 및 이상 징후를 탐지한 뒤, PatternOps 계약, 유사 사례, Knowledge Card, semantic cluster, trajectory를 참고해 장애 원인/영향/조치 방향을 제안하는 멀티 에이전트 시스템 |
| **핵심 목표** | 장애 가능성을 조기에 탐지하고, 관측 증거에 연결된 안전한 수정 방향과 검증 및 재발 방지 방안을 제시 |
| **톤앤매너** | SRE/백엔드 엔지니어에게 보고하듯 간결하고 근거 중심적으로 답변. 사용자 표시 내용은 한국어를 기본으로 하며, 관측 사실과 추론을 구분하고 불확실한 부분은 confidence와 추가 필요 데이터로 명시 |
| **제약 사항** | 인프라 변경, 임의 DB 스키마 변경, 시크릿/인증 정보 회전, 파괴적 운영 명령, 근거 없는 원인 단정 금지. 증거가 부족하면 추정하지 않고 `additional_data_needed`로 분리 |

**1.1 에이전트 워크플로우 (Agent Workflow)**

- **구현 기능:** 서비스 로그 분석 요청의 범위를 초기화하고, 로그 수집 → 정규화/fingerprint 및 패턴 분석 → 이상 탐지를 순차 조율한 뒤 deterministic scenario 분석과 RAG 조회 결과를 하나의 `SharedState`로 통합한다. 사용자가 fingerprint를 선택하면 별도 Recommendation workflow를 실행한다.

- **동작 원리:** `POST /analyze`가 요청별 상태를 생성하면 `OrchestratorAgent`가 전역 SkillOps plan과 `completed_agents`를 확인해 다음 worker를 선택한다. 각 worker는 scope별 skill graph에서 자신에게 연결된 operation을 실행하고 다시 Orchestrator로 복귀한다. 기본 분석 이후 API 레이어가 risk, cluster, time window, state vector, trajectory를 보강한다. 선택 fingerprint 권고에서는 Knowledge Card 검색 → 구조화 권고 생성 → 품질 평가 순으로 처리한다.

- **주요 기술:** FastAPI, LangGraph `StateGraph`, conditional edge, Python `TypedDict` 기반 `SharedState`, Orchestrator pattern, PatternOps/SkillOps runner, retry/fallback, SSE, LangSmith/local trace.

**1.2 도구(Tool) 및 함수 연동**

- **구현 기능:** SQLite 로그/분석/권고 데이터 조회·저장, ChromaDB 유사 지식 검색·저장, OpenAI 기반 구조화 권고 생성, deterministic detection pipeline 및 패턴 정규화 rule 제안을 연동한다.

- **동작 원리:** 외부 API 입력은 `AnalyzeRequest`, `FingerprintRecommendationRequest`, `ApprovalRequest` 등의 Pydantic 모델로 먼저 검증한다. Agent는 단일 in-process `MCPClient`를 통해 이름 기반 tool을 호출하고, `MCPServer`는 tool별 handler에서 `arguments`를 명시적인 Python 타입으로 변환한 뒤 SQLite/ChromaDB/OpenAI adapter에 전달한다. deterministic pipeline과 `PatternRuleSuggestionAgent`는 애플리케이션 레이어에서 직접 호출한다.

- **주요 기술:** Pydantic v2, FastAPI request/response model, in-process MCP-style registry, OpenAI Responses API wrapper, SQLite, ChromaDB `PersistentClient`, Python exception handling 및 graceful fallback.

**1.3 데이터 및 메모리 (RAG & Context)**

- **구현 기능:** 분석 목표, anomaly pattern, fingerprint, Known Pattern 및 승인된 Knowledge Card를 이용해 유사 장애 사례를 검색하고 Recommendation evidence로 제공한다. Pattern template과 장애 진행 trajectory도 별도 분석 증거로 관리한다.

- **동작 원리:** 한 요청 안에서는 `SharedState`가 context를 유지한다. 장기 지식은 SQLite와 ChromaDB에 저장한다. 임베딩 설정이 있으면 pattern은 1024차원, case/knowledge 문서는 1536차원으로 embedding하여 목적별 v2 collection에서 검색하고, 설정이 없거나 결과가 없으면 legacy collection으로 fallback한다. 선택 fingerprint 권고에서는 exact fingerprint Knowledge Card와 semantic 유사 Knowledge Card를 병합한다.

- **주요 기술:** ChromaDB, OpenAI/Azure OpenAI Embeddings, 기본 `text-embedding-3-large`, metadata filtering, similarity search, Knowledge Card, purpose-specific collections, request-scoped context, batch embedding 및 fallback retrieval.

### 워크플로우 및 오케스트레이션 (Workflow & Logic)

**2.1 처리 로직**

* **Step 1 (Input Analysis):**

  * `POST /analyze` 요청의 `service_name`, `goal`, `analysis_date`, `scope`, `save_to_chromadb`, `include_similar_clusters`, `include_time_windows`를 기반으로 `SharedState`를 초기화한다.

  * 전달된 `scope`가 있더라도 `scope.systems`는 요청의 `service_name` 하나로 고정하고, `scope.time_range.from/to`는 `analysis_date` 하루로 설정한다.

  * `analysis_date`가 없으면 서버의 현재 날짜를 사용하며, 요청별 `request_id`를 새로 생성한다.

* **Step 2 (Skill Selection & Orchestration):**

  * LangGraph의 `OrchestratorAgent`는 `LogCollectorAgent → LogAnalysisAgent → AnomalyDetectionAgent` 순서를 기준으로 다음 Agent를 선택한다.

  * 실제 실행 여부는 `plan_skill_graphs(...)`가 선택한 전역 skill과 각 Agent의 skill map 교집합으로 결정된다.

  * 각 worker Agent는 `pattern_skill_runner.run_for_agent(...)`를 통해 scope별 PatternOps/SkillOps skill을 선택하고, Agent가 제공한 operation callable을 실행한다.

  * `LogAnalysisAgent`의 대표 skill은 `log_normalization`, `pattern_fingerprint`, `known_pattern_match`, `duplicate_pattern_detection`, `fingerprint_merge`, `pattern_rule_suggestion`이다.

  * `RecommendationAgent`의 대표 skill은 `knowledge_card_retrieval`, `recommendation_generation`, `recommendation_quality_gate`이며 기본 `/analyze`가 아니라 선택 fingerprint 권고 API에서 실행된다.

* **Step 3 (Execution & Response):**

  * LangGraph 실행 뒤 `run_detection_pipeline(...)`이 deterministic scenario 분석을 수행한다.

  * 로그, fingerprint, anomaly, risk, PatternOps, cluster, event time window, system state vector, semantic cluster, trajectory 결과를 `SharedState.evidence`와 `final.evidence_bundle`에 통합한다.

  * 기본 `/analyze`에서는 `RecommendationAgent`를 실행하지 않고 `decisions.skipped_agents`에 기록한다. `evidence.recommendation`은 LLM 상세 권고가 아니라 deterministic recommendation hint이다.

  * `KnowledgeBaseRAGAgent`가 ChromaDB 유사 지식을 조회한다. `save_to_chromadb=true`여도 `final.generated_answer`가 없으면 최종 답변을 저장하지 않는다.

  * 선택 fingerprint의 상세 권고는 `POST /recommendations/fingerprint`에서 생성하며 자동 저장하지 않는다. 사용자가 `POST /recommendations/save`를 호출해야 권고 이력이 SQLite에 저장된다.

**2.2 상태 관리**

**대화 턴(Turn) 관리를 위한 상태 정의**

* 현재 시스템은 장기 대화 세션보다 요청 단위 공유 상태인 `SharedState`를 중심으로 동작한다.

* 각 API 요청마다 새 `request_id`와 상태를 생성하며, LangGraph checkpoint나 사용자별 conversation history는 사용하지 않는다.

| 상태 영역 | 관리 내용 |
| --------------- | ------------------------------------------------------------------- |
| `goal` | 사용자의 분석 목표 |
| `request_id` | 요청 단위 추적 ID |
| `scope` | 분석 대상 서비스, 날짜 범위, fingerprint/stack trace 관련 filters |
| `evidence` | 로그, fingerprint, Known/New Pattern, PatternOps 계약·계획·실행·validator, anomaly, cluster, trajectory, stack trace, incident/source evidence |
| `metrics` | `error_rate`, `latency_p95`, `rps`, `anomaly_score` |
| `assessment` | `risk_score`, `confidence`, 판단 근거 |
| `decisions` | 실행/스킵 Agent, assumptions, failures, timeouts |
| `orchestration` | 다음 실행 대상, pending/completed Agent |
| `preferences` | `save_to_chromadb` 설정 |
| `rag` | ChromaDB 유사 지식 조회 결과 및 저장 여부 |
| `final` | 최종 요약, 권고 조치, 검증 단계, 추가 필요 데이터, 생성 답변, evidence bundle, 저장 ID |

* 최신 분석 증거에는 `event_time_windows`, `system_state_vectors`, `semantic_clusters`, `fingerprint_merge_groups`, `trajectories`, `trajectory_clusters`, `nearest_trajectory_patterns`가 포함된다.

* 런타임 상태에는 `pattern_clusters`와 Recommendation 관련 동적 evidence key도 추가되지만 일부는 현재 `Evidence` TypedDict 선언에 명시되지 않아 정적 타입과 실제 payload가 완전히 일치하지 않는다.

**LangGraph Node/Edge 흐름 기술**

* 현재 `POST /analyze`가 사용하는 graph는 `app.graph.engine.build_graph`이다.

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

* 전역 skill plan에 해당 Agent가 실행할 skill이 없으면 Agent를 건너뛸 수 있으므로 위 흐름은 기본 우선순위다.

* 각 node는 최초 실행 후 1회 재시도한다. 최종 실패하면 `decisions.failures`, `decisions.skipped_agents`, `orchestration.completed_agents`에 기록하고 전체 흐름을 계속한다.

* 실행 skill의 계획, 이력, 검증 결과는 `evidence.pattern_ops_skill_plan`, `evidence.pattern_ops_skill_executions`, `evidence.pattern_ops_validator_results`에 저장된다.

* `app.graph.builder`의 `LogCollector → LogAnalysis → Recommendation` graph는 레거시 `/agents/run` 흐름이며 기본 `/analyze` graph와 다르다.

### 도구(Tools) 및 함수 명세 (Capability)

| 도구명 (Function Name) | 기능 설명 (Description) | 입력 파라미터 (Input Schema) | 출력 데이터 (Output) |
| ------------------------------------ | --------------------------------------------------------------------- | ----------------------------------------------------- | ----------------------------------------------------------- |
| `sqlite.fetch_recent_logs` | 최근 로그 메시지 조회. 레거시 `/agents/run` 흐름에서 사용 | `service_name: str`, `limit: int` | `list[str]` |
| `sqlite.fetch_recent_log_entries` | 서비스별 최근 구조화 로그 조회 | `service_names: list[str]`, `limit: int` | `list[dict]` |
| `sqlite.save_log_analysis` | 로그 분석 결과 저장 | `goal: str`, `service_name: str`, `analysis: str` | `None` |
| `sqlite.fetch_latest_log_analyses` | 최근 로그 분석 결과 조회 | `service_names: list[str]`, `limit: int` | `list[dict]` |
| `sqlite.save_impact_evaluation` | 위험도, 신뢰도, 판단 근거 저장 | `service_name`, `risk_score`, `confidence`, `rationale` | `None` |
| `sqlite.save_recommendation_result` | 사용자가 명시적으로 선택한 권고 이력 저장 | 추천 내용, actions, verification, evidence, risk | `int \| None` |
| `sqlite.fetch_latest_recommendation_results` | 저장된 권고 이력 조회 | `service_names: list[str]`, `limit: int` | `list[dict]` |
| `chromadb.find_related_analyses` | ChromaDB 유사 분석/Knowledge Card 조회 | `query: str`, `n_results: int` | `list[str]` |
| `chromadb.save_analysis_document` | 최종 답변 또는 지식 문서 저장 | `doc_id: str`, `text: str`, `metadata: dict` | `bool` |
| `openai.generate_text` | OpenAI Responses API 기반 텍스트/JSON 생성 | `messages: list`, `model?: str`, `temperature: float` | `str` |
| `run_detection_pipeline` | fingerprint, anomaly, risk, cluster, trajectory, recommendation hint 등의 deterministic 시나리오 분석 | `service_name`, `analysis_date`, `include_time_windows` | `summary`, `fingerprints`, `anomalies`, `impacts`, `trajectories` 등 |
| `PatternRuleSuggestionAgent.propose` | 로그 메시지 기반 정규화 regex/template 제안 | `cluster: str`, `message: str` | `{name, match_regex, template, confidence, reason}` |

* 위 표의 `sqlite.*`, `chromadb.*`, `openai.*` 항목은 현재 in-process `MCPServer`에 실제 등록된 도구다.

* `run_detection_pipeline`과 `PatternRuleSuggestionAgent.propose`는 MCP 도구가 아니라 API/애플리케이션 레이어에서 직접 호출하는 함수다.

* 현재 MCP registry에는 Microsoft Graph 도구가 없다.

### 지식 베이스 및 메모리 전략 (Context & Memory)

**4.1 RAG (검색 증강 생성) 전략**

* **참조 데이터 소스:** SQLite 기반 service logs, 분석 결과, recommendation history, Known Pattern, exception registry, accepted normal pattern, Knowledge Card, PatternOps 데이터와 ChromaDB vector documents.

* **청킹(Chunking) 방식:** 별도 범용 토큰 chunker는 사용하지 않는다. Pattern cluster는 service/fingerprint/level/status/normalized message/context를 구조화한 문서 단위로 저장하고, Knowledge Card/Known Pattern/Incident Summary는 case 단위 문서로 저장한다.

* **임베딩 모델:** 기본 `text-embedding-3-large`. OpenAI 또는 Azure OpenAI provider를 사용할 수 있다. Pattern embedding은 기본 1024차원, Case Card/Known Pattern/Incident Summary는 기본 1536차원이다.

* **Vector DB:** ChromaDB `PersistentClient`. 경로는 `CHROMADB_PATH`로 설정한다.

* **주요 collection:** `pattern_templates_v2`, `case_cards_v2`, `known_patterns_v2`, `incident_summaries_v2`, legacy `pattern_clusters`, `incident_analyses`.

* **검색 fallback:** embedding 설정이 없거나 v2 결과가 없으면 legacy collection 경로를 사용한다.

* **선택 fingerprint RAG:** 정확 fingerprint Knowledge Card와 semantic 유사 Knowledge Card를 결합하고, Recommendation evidence에 참조 ID를 포함한다.

**4.2 대화 메모리 (Conversation History)**

* **메모리 유형:** 요청 단위 `SharedState`와 DB/ChromaDB 기반 장기 지식을 결합한다.

* **단기 저장 전략:** 한 API 요청 동안 Agent와 skill 실행 결과를 `SharedState`에 누적하고 응답 후 종료한다.

* **장기 저장 전략:** `POST /approvals`는 실제 해결 결과를 Knowledge Card와 PatternOps case contract로 캡처한다. `POST /recommendations/save`는 사용자가 명시적으로 저장한 권고만 이력화한다.

* **ChromaDB 저장 조건:** `KnowledgeBaseRAGAgent.persist_final_answer()`는 `save_to_chromadb=true`이고 `final.generated_answer`가 있을 때만 저장한다.

* **모니터링 이력:** Agent 실행은 선택적으로 LangSmith에 기록하며, 비활성화되었거나 조회할 수 없으면 로컬 trace event buffer를 사용한다.

### 핵심 에이전트 기술 스택

| 구분 | 선정 전략/기술 | 선정 사유 (논리적 근거) |
| -------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------- |
| **LLM Model** | `OPENAI_MODEL`, 미설정 기본값 `gpt-4o-mini`; `LLM_STUB_MODE` 지원 | 모델을 환경별로 교체할 수 있고 로컬/테스트에서는 stub 응답으로 외부 호출을 분리 |
| **Embedding Model** | 기본 `text-embedding-3-large`, OpenAI/Azure OpenAI 선택 | 한국어/영어 혼합 로그 및 유사 장애 지식 검색에 사용하며 목적별 차원 축소 지원 |
| **Agent Framework** | LangGraph `StateGraph` | Orchestrator 중심 조건부 라우팅, 상태 공유, 재시도와 실패 기록을 명확하게 관리 |
| **Prompt Strategy** | Deterministic-first + evidence-grounded structured prompt + quality gate | 로그 정규화/탐지는 재현 가능한 코드로 수행하고 LLM은 상세 권고 생성과 평가에 집중 |
| **Output Parsing** | JSON object 파싱 + schema/hard-fail 검증 | UI와 저장소가 요구하는 정형 권고 필드를 안정적으로 확보 |
| **Quality Control** | 100점 rubric, 80점 통과, 최대 3회 생성/평가 | 근거 연결, 실행 가능성, 검증/예방 단계, 안전성을 평가하고 미통과 시 best-effort/fallback 제공 |
| **Monitoring** | `LOG_LEVEL` + local trace buffer + optional LangSmith + SSE | Agent/skill의 시작, 완료, 재시도, 실패 및 실시간 분석 진행 상황 추적 |
| **RAG / Memory** | ChromaDB + Knowledge Card + PatternOps Registry | 유사 장애 사례와 승인된 해결책을 fingerprint/semantic 기준으로 재사용 |
| **Structured Persistence** | 현재 SQLite | 로그, 패턴, 예외, 승인 지식, 권고 이력을 구조화 저장. PostgreSQL client는 현재 코드에서 사용하지 않음 |
| **Operational Guardrails** | 금지 제안 hard-fail + 권고 명시적 저장 | 인프라 변경, DB 스키마 변경, 시크릿 회전, 파괴 명령을 차단하고 사용자 승인 없는 이력 저장 방지 |

### 현재 구현 기준 Agent 매핑

| 개념상 Agent | 현재 구현 상태 |
| ------------ | ------------- |
| Log Collector Agent | `LogCollectorAgent`로 구현되어 기본 LangGraph 흐름에 포함 |
| Log Analysis Agent | `LogAnalysisAgent`로 구현되어 정규화, fingerprint, Known/New Pattern, PatternOps match, cluster 산출 |
| Anomaly Detection Agent | `AnomalyDetectionAgent`로 구현되어 suppression 이후 반복·증감·부재·신규 패턴 이상 탐지 |
| Impact Evaluation Agent | 독립 Agent/node가 없으며 deterministic pipeline의 impact/risk와 `assessment`로 표현 |
| Source Code Analysis Agent | prompt 상수와 `source_code_evidence` 확장 필드만 있고 독립 Agent는 미구현 |
| Recommendation Agent | 기본 `/analyze`에서는 skip되고 `POST /recommendations/fingerprint`에서 실행 |
| KnowledgeBaseRAGAgent | ChromaDB 유사 지식 조회 및 조건부 최종 답변 저장 담당 |
| PatternRuleSuggestionAgent | 패턴 정규화 regex/template 제안 담당 |

### Recommendation 출력 및 품질 기준

* **출력 형식:** `executive_summary`, `root_cause_analysis`, `impact_analysis`, `recommended_actions`, `verification_steps`, `prevention_steps`, `additional_data_needed`, `referenced_knowledge_card_ids`, `confidence`를 포함하는 JSON object.

* **권고 action 필드:** `priority`, `action`, `reason`, `target`, `owner`, `expected_effect`, `risk`, `evidence`.

* **평가 배점:** Evidence-linked RCA 25점, 실행 가능한 조치 25점, 검증 단계 20점, 예방 단계 15점, 안전성 15점.

* **Hard Fail:** 구체 증거 없는 원인 분석, 필수 조치 근거/대상/효과/위험 누락, 검증 단계 2개 미만, 예방 단계 누락, 인프라·스키마·시크릿·파괴적 조치 포함.

* **실패 처리:** 최대 3회 안에 80점을 통과하지 못하면 최고 점수 결과를 `best_effort`로 사용한다. 생성/파싱/평가 실패 시 deterministic fallback을 반환하고 사유를 `decisions.assumptions`에 기록한다.

### 주요 문제 해결 및 기술 리서치

구현 과정에서 확인한 문제와 실제 코드에 적용한 해결 방법은 다음과 같다.

| | | |
| --------- | ------------------------------------ | ----------------------------------------------------------------------------------------- |
| **이슈 구분** | **문제 상황 및 원인** | **리서치 및 해결 과정 (Reference & Solution)** |
| **워크플로우** | 단순 순차 함수 호출만으로는 Agent별 실행 상태, 조건부 skip, 실패 및 재시도를 일관되게 추적하기 어려웠다. | • **리서치:** [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)의 shared state, node, edge, conditional edge 구조 확인<br>• **적용:** `StateGraph(SharedState)`와 `OrchestratorAgent`를 도입하고 `pending_agents`, `completed_agents`, `skipped_agents`, `failures`를 상태에 기록. worker 종료 후 Orchestrator로 복귀하도록 구성 |
| **프롬프트/품질** | LLM 권고가 일반론에 머물거나 근거 없는 원인과 위험한 운영 조치를 포함할 수 있었다. | • **리서치:** 자유 형식 답변보다 evidence-grounded structured output과 별도 evaluator를 사용하는 test-time loop 검토<br>• **적용:** JSON object schema, 100점 rubric, 80점 기준, hard-fail, 최대 3회 재생성, best-effort/fallback을 구현. 인프라·DB schema·secret·파괴 명령 제안을 차단 |
| **도구 연동** | API 입력과 내부 tool `arguments`의 타입/필수값이 섞이면 런타임 포맷 오류가 발생하기 쉬웠다. | • **리서치:** [FastAPI Request Body](https://fastapi.tiangolo.com/tutorial/body/)의 Pydantic 기반 검증 방식 확인<br>• **적용:** API 경계는 Pydantic model로 검증하고 MCP handler는 `str`, `int`, `float`, `list`, `dict`를 명시 변환. 알 수 없는 tool name은 즉시 `ValueError` 처리 |
| **RAG 검색** | 서로 성격이 다른 Pattern Template, Knowledge Card, Known Pattern, Incident Summary를 한 collection에 넣으면 metadata와 검색 결과가 섞일 수 있었다. | • **리서치:** [Chroma 컬렉션 데이터 추가](https://docs.trychroma.com/docs/collections/add-data)와 [컬렉션 조회](https://docs.trychroma.com/docs/querying-collections/query-and-get) 동작 검토<br>• **적용:** `pattern_templates_v2`, `case_cards_v2`, `known_patterns_v2`, `incident_summaries_v2`로 분리하고, v2 검색 실패 시 legacy collection으로 fallback |
| **임베딩 성능** | 모든 문서에 큰 embedding 차원을 고정하면 pattern template처럼 짧은 문서에도 저장 공간과 호출 비용이 커진다. | • **리서치:** OpenAI Embeddings API의 `text-embedding-3` 계열 [`dimensions` parameter](https://platform.openai.com/docs/api-reference/embeddings/create) 확인<br>• **적용:** pattern은 기본 1024차원, case/knowledge 문서는 기본 1536차원으로 분리하고 환경변수로 조정 가능하게 구성. batch embedding과 기존 ID skip 적용 |
| **패턴 분산** | request ID, 숫자, URL, 파일 경로, timestamp 같은 volatile 값 때문에 동일 장애가 여러 fingerprint로 갈라졌다. | • **리서치:** 정규식 기반 template normalization, 구조/token/stack 유사도, embedding similarity의 혼합 전략과 저장소 내 [로그 trajectory 설계 가이드](./log_trajectory_clustering_guide.md) 검토<br>• **적용:** `normalize_log_text()`, SHA-256 fingerprint, rule suggestion, duplicate candidate, manual/approved merge와 canonical alias를 구현 |
| **정상 피드백** | 운영자가 정상으로 승인한 반복 패턴을 exception처럼 숨기면 관측 가능성이 사라지고, 이후 임계치 초과도 탐지할 수 없었다. | • **리서치:** exception과 accepted baseline의 역할을 분리한 저장소 내 [Accepted Normal 설계](./accepted_normal_patterns_claude_instruction.md) 검토<br>• **적용:** accepted normal은 fingerprint 목록에 계속 표시하되 anomaly count에서는 제외하고, 허용 count/multiplier 초과 시 `ACCEPTED_NORMAL_BREACH`로 재탐지 |
| **성능/기타** | 회귀 테스트에서 timezone 없는 `datetime.utcnow()` 사용과 TestClient/httpx 호환성 deprecation warning이 발생한다. | • **확인:** 대표 테스트 실행 시 기능 실패 없이 warning 39건 확인<br>• **후속 조치:** `datetime.now(datetime.UTC)`로 전환하고 Starlette/FastAPI 테스트 client 의존성 호환 범위를 정리할 필요가 있음. 현재 기능 동작에는 영향 없음 |

### 핵심 동작 검증

아래 결과는 2026-07-13에 다음 대표 테스트를 실행해 확인했다.

```text
cd LOG_DETECT_AGENTS_BACK
pytest app/tests/test_graph_e2e.py tests/test_recommendation_agent.py tests/test_accepted_normal_patterns.py -q
11 passed, 39 warnings in 169.18s
```

**[검증 시나리오: 서비스 로그 분석 요청의 Agent 라우팅]**

- **입력:** `service_name="billing-api"`, `goal="payment auth exception risk investigation"`, `save_to_chromadb=false`

- **에이전트 동작:**

1. `create_initial_state(...)`가 요청 단위 `SharedState`를 생성한다.

2. `OrchestratorAgent`가 `LogCollectorAgent`, `LogAnalysisAgent`, `AnomalyDetectionAgent`를 skill plan에 따라 실행한다.

3. deterministic pipeline이 fingerprint, anomaly, risk 및 evidence bundle을 보강한다.

4. `KnowledgeBaseRAGAgent`가 관련 지식을 조회한다.

5. 기본 분석이므로 `RecommendationAgent`는 skip하고 LLM 상세 권고를 생성하지 않는다.

- **최종 결과:** HTTP 200을 반환하고 `AnomalyDetectionAgent`, `KnowledgeBaseRAGAgent`가 `agents_run`에 포함된다. `RecommendationAgent`는 `skipped_agents`에 포함되며, `final.generated_answer=null`, `final.evidence_bundle`은 생성되고 `rag.saved_to_chromadb=false`로 유지된다.

**[검증 시나리오: 선택 fingerprint의 LLM 권고 및 품질 게이트]**

- **입력:** payment provider timeout anomaly, risk score 82, `payment_client.py::PaymentClient.call` source evidence, Knowledge Card `KC-123`이 포함된 선택 fingerprint 상태

- **에이전트 동작:**

1. `knowledge_card_retrieval`이 관련 Knowledge Card와 참조 ID를 evidence에 연결한다.

2. `recommendation_generation`이 원인, 영향, action, 검증 및 예방 단계를 JSON으로 생성한다.

3. `recommendation_quality_gate`가 evidence 연결, 실행 가능성, 검증, 예방, 안전성을 평가한다.

4. 80점 이상이고 hard-fail이 없으면 통과한다. 낮은 품질이면 evaluator feedback을 반영해 재생성한다.

- **최종 결과:** 정상 권고는 `quality_score=86`, `quality_gate_status="passed"`, `quality_attempts=1`로 통과했다. 첫 평가가 72점인 사례는 2회차에 84점으로 통과했고, 잘못된 JSON이 반복된 사례는 `recommendation_source="fallback"`, `quality_gate_status="fallback"`으로 안전하게 종료됐다. 권고는 자동 저장되지 않아 `saved_recommendation_id=null`이다.

**[검증 시나리오: 이상 패턴의 Accepted Normal 편입과 임계치 초과 재탐지]**

- **입력:** `batch-service`에서 과거 일 2건 수준이던 동일 ERROR가 분석일 10건으로 증가한 spike fingerprint

- **에이전트 동작:**

1. 최초 pipeline이 해당 fingerprint를 실제 anomaly로 탐지한다.

2. 운영자가 `register_accepted_normal_pattern(...)`으로 정상 기준선에 편입한다.

3. 재분석 시 fingerprint는 목록에 유지하지만 anomaly 목록과 count에서는 제외한다.

4. 이후 occurrence count가 승인된 `max_allowed_count`를 넘으면 breach로 재평가한다.

- **최종 결과:** 기준 범위 안에서는 `accepted_normal=true`, `anomaly_type="ACCEPTED_NORMAL"`, `accepted_normal_count=1`로 표시된다. 허용 수량을 넘긴 뒤에는 `anomaly_type="ACCEPTED_NORMAL_BREACH"`, `accepted_normal_breach_count=1`이 되고 anomaly 목록에 다시 포함된다. revoke 후에는 정상 편입이 더 이상 적용되지 않는다.

### 현재 코드 기준 유의사항

* 현재 실제 구조화 저장소는 SQLite다. 최상위 설계의 PostgreSQL은 목표 아키텍처이며, `POSTGRESQL_URL`은 현재 PostgreSQL client 연결에 사용되지 않는다.

* 기본 분석은 deterministic-first 구조다. LLM은 전체 로그 탐지보다 선택 fingerprint의 상세 권고 생성과 평가에 집중한다.

* Source Code Analysis Agent는 아직 구현되지 않았으므로 소스 영향 범위 분석을 완료 기능으로 표현하면 안 된다.

* `app.graph.builder`는 레거시 `/agents/run`용이고, 기본 `/analyze`는 `app.graph.engine`의 Orchestrator graph를 사용한다.

## **주요 문제 해결 및 기술 리서치 (테스트 단계)**

테스트 과정에서 발견된 edge case와 반복 처리 병목을 기준으로, 현재 코드에 실제 적용된 해결 방법을 정리한다. 아래 내용에는 Redis, 병렬 tool calling, 별도 prompt-injection detector처럼 현재 시스템에 없는 기능이나 측정하지 않은 성능 수치를 포함하지 않는다.

| **이슈 구분** | **문제 상황 및 원인** | **리서치 및 해결 과정 (Reference & Solution)** |
| ----------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| **품질/환각** | LLM evaluator가 높은 점수를 주더라도 원인 근거, action 세부 필드, 검증 및 예방 단계가 빠진 답변이 통과할 수 있었다. | • **리서치:** evaluator 점수만 사용하는 방식의 한계를 확인하고 structured output, deterministic validation, test-time regeneration 조합을 검토<br>• **적용:** evaluator와 별개로 `_hard_fail_reasons()`를 실행해 evidence 연결, action 필드, 검증 2개 이상, 예방 단계, 금지 조치를 검사. 테스트에서는 evaluator가 92점을 준 불완전 답변도 거절하고 재생성된 84점 답변을 채택 |
| **출력 파싱** | OpenAI 응답이 JSON이 아니거나 필수 구조를 만족하지 않으면 Recommendation workflow 전체가 실패할 수 있었다. | • **리서치:** schema-constrained prompt와 parser 실패 시 graceful degradation 방식 검토<br>• **적용:** JSON object 단일 출력 지시, custom parser/validator, 최대 3회 재시도 후 deterministic fallback 적용. 연속 `not-json` 응답 테스트에서 `recommendation_source="fallback"`으로 정상 종료 |
| **검색 정확도** | embedding similarity만 높고 message 구조가 다른 로그가 동일 패턴이나 duplicate candidate로 잘못 묶일 수 있었다. | • **리서치:** semantic similarity와 lexical/structural evidence를 결합하는 hybrid matching 검토<br>• **적용:** token, 구조, stack trace, metadata, embedding score를 함께 평가하고 pattern similarity가 낮으면 높은 embedding score만으로 Known/duplicate 판정을 덮어쓰지 않도록 제한 |
| **임베딩 속도/비용** | pattern 또는 query마다 embedding API를 개별 호출하면 collection 수와 fingerprint 수에 비례해 호출 횟수가 증가한다. | • **리서치:** OpenAI embedding batch input과 Chroma query embedding 재사용 방식 검토<br>• **적용:** 저장과 검색 모두 batch 처리하고, analysis query embedding은 여러 v2 collection에서 재사용. 이미 존재하는 document ID는 embedding 대상에서 제외하고 batch 실패 시 반으로 분할해 실패 item을 격리 |
| **반복 분석 성능** | 같은 서비스/날짜/옵션을 다시 분석할 때 정규화, clustering, RAG query를 전부 재실행하는 비용이 발생한다. | • **리서치:** deterministic pipeline 결과 cache와 incremental processing 방식 검토<br>• **적용:** `_PIPELINE_CACHE`에 결과를 저장하고 반환 시 `deepcopy`하여 호출자 변형을 차단. 신규 raw log만 처리하고, normalization rule·exception·accepted normal·merge 등 결과에 영향을 주는 mutation 시 cache를 clear |
| **클러스터 fallback** | embedding API key가 없거나 embedding/HDBSCAN 결과를 만들 수 없으면 semantic cluster가 비어 downstream evidence가 약해질 수 있었다. | • **리서치:** template 기반 deterministic clustering을 fallback으로 사용하는 방식 검토<br>• **적용:** OpenAI embedding/HDBSCAN을 사용할 수 없을 때 Drain3 template 기반 `drain3_template_fallback` cluster를 생성 |
| **보안/가드레일** | 생성 권고가 인프라 변경, 임의 DB schema 변경, secret/credential rotation 또는 파괴적 명령을 포함할 가능성이 있다. | • **리서치:** prompt-level 정책만으로 차단하지 않고 생성 후 deterministic policy check를 병행하는 방식 검토<br>• **적용:** prompt 금지 지시 + evaluator safety 항목 + 금지어 hard-fail을 중첩 적용. 권고 이력은 생성 즉시 저장하지 않고 사용자가 `/recommendations/save`를 호출할 때만 저장 |
| **운영 피드백** | accepted normal을 exception과 동일하게 숨기면 이후 occurrence 증가를 관측하거나 breach로 재탐지할 수 없다. | • **리서치:** suppression과 observable baseline을 분리하는 feedback loop 검토<br>• **적용:** exception은 분석 목록에서 제외하고 accepted normal은 목록에 유지. 승인 범위 초과 시 `ACCEPTED_NORMAL_BREACH`, revoke 시 기존 anomaly 판정으로 복귀하도록 테스트 |

## 1. LLM 답변 품질 평가 및 개선

| 항목 | 내용 |
| -------- | ------------------------------------------------------------------- |
| 평가 대상 기능 | 선택 fingerprint에 대한 RAG/evidence 기반 상세 권고 생성 |
| 평가 데이터 | `payment-api` timeout fingerprint, anomaly, risk score, source evidence, Known Pattern, Knowledge Card를 조합한 고정 테스트 fixture. 현재 별도 Ground Truth 30건 데이터셋은 없음 |
| 평가 방식 | LLM evaluator의 100점 rubric과 deterministic hard-fail을 함께 사용. RCA 근거 25점, action 실행 가능성 25점, 검증 20점, 예방 15점, 안전성 15점 |
| 통과 기준 | 총점 80점 이상이면서 hard-fail 사유가 없어야 함 |
| 초기 문제 | 약한 권고가 72점으로 기준 미달하거나, 불완전한 답변이 evaluator에서 92점을 받아도 필수 action/검증/예방 구조가 누락되는 edge case 확인 |
| 개선 조치 | evaluator feedback을 다음 생성 prompt에 전달하여 최대 3회 재생성하고, `_hard_fail_reasons()`로 점수와 무관한 필수 조건을 강제. evidence bundle에 quality score/status/attempts/feedback을 기록 |
| 개선 후 결과 | 정상 fixture는 86점, 1회차 통과. 72점 답변은 feedback 반영 후 2회차 84점으로 통과. evaluator 92점의 불완전 답변은 hard-fail로 거절하고 다음 84점 답변을 채택 |
| 파싱 실패 결과 | 연속 비정형 응답은 예외로 workflow를 중단하지 않고 deterministic fallback으로 전환. `quality_gate_status="fallback"`과 assumption을 기록 |
| 현재 한계 | Faithfulness/Relevance를 독립 Ground Truth 데이터셋으로 측정하는 평가 harness는 아직 없음. 현재 수치는 Recommendation rubric fixture 결과이며 RAG 전체 정확도 백분율이 아님 |

## 2. 성능 및 비용 최적화

| 항목 | 내용 |
| ----- | ---------------------------------------- |
| 기존 병목 | fingerprint별 embedding 저장, query별 collection 반복 embedding, 로그 row마다 Drain3 miner 생성, 동일 조건 pipeline 재실행 |
| 개선 전략 | batch embedding/query, query embedding 재사용, 기존 ID skip, batch 실패 분할, miner batch 재사용, pipeline result cache, 신규 raw log incremental 처리 |
| 적용 기술 | OpenAI/Azure OpenAI Embeddings batch input, ChromaDB batch upsert/query, `_PIPELINE_CACHE`, `functools.lru_cache`, `copy.deepcopy`, Drain3 batch template mining |
| 검색 최적화 | `find_similar_pattern_clusters_batch()`는 query 목록을 한 번에 embedding하고, `find_similar_analysis_documents_batch()`는 생성한 query embedding을 case/known/incident collection에 재사용 |
| 저장 최적화 | v2 collection의 기존 ID를 먼저 확인해 이미 저장된 문서는 embedding과 upsert를 건너뜀. 실패 batch는 재귀적으로 나눠 정상 item 저장을 계속하고 실패 item만 기록 |
| 분석 최적화 | 동일 cache key는 pipeline 결과 복사본을 반환하며, 재실행 시 신규 raw log만 처리한 수를 metrics로 추적. `include_time_windows=false`, `include_similar_clusters=false`로 선택적 고비용 분석 생략 가능 |
| 테스트 결과 | batch query가 여러 query에 대해 embedding client를 한 번 호출하는지, analysis query embedding을 여러 collection에서 재사용하는지, Drain3 miner가 로그 row별이 아닌 한 batch로 실행되는지, 기존 ID가 skip되는지를 단위 테스트로 검증 |
| 정량 결과 | 현재 저장소에는 최적화 전후 latency·token·API 비용을 동일 조건으로 측정한 benchmark 결과가 없어 “몇 초 단축” 또는 “몇 % 절감” 수치는 제시하지 않음 |
| 현재 한계 | cache는 프로세스 메모리 기반으로 worker 간 공유되지 않으며 Redis/Semantic Cache는 사용하지 않음. LangGraph worker와 MCP tool은 현재 동기 순차 실행이며 `asyncio` 병렬 tool calling은 적용되지 않음 |

## 3. 예외 처리 및 가드레일

| 항목 | 내용 |
| ------ | ------------------------------- |
| 권고 차단 대상 | 인프라 변경, 임의 DB schema 변경, secret/credential rotation, 파괴적 명령, 구체 evidence 없는 원인 단정, 필수 검증/예방 단계가 없는 조치 |
| 탐지 방식 | Recommendation system prompt의 금지 지시, LLM evaluator safety 점수, 생성 결과의 deterministic `_hard_fail_reasons()` 검사 |
| 입력 검증 | FastAPI/Pydantic 모델로 필수값, 문자열 최소 길이, list 최소 개수와 날짜 타입 등을 검증. MCP registry에 없는 tool name은 `ValueError` 처리 |
| 출력 검증 | JSON object parsing, action 필수 key 검사, verification 최소 2개, prevention 존재 여부, evidence anchor와 금지어 검사 |
| 대응 로직 | 품질 미달 시 evaluator feedback을 포함해 최대 3회 재생성. 계속 실패하면 최고 점수 결과를 `best_effort`로 반환하고, 생성/파싱 자체가 불가능하면 안전한 fallback 반환 |
| Agent 오류 처리 | graph node는 한 번 재시도하고 최종 실패를 `decisions.failures`와 `skipped_agents`에 기록한 뒤 전체 분석을 계속하는 graceful degradation 적용 |
| 데이터 보호 | 권고 preview는 자동 저장하지 않는다. `/recommendations/save`와 `/approvals` 같은 명시적 사용자 동작에서만 추천 이력 또는 승인 지식을 저장 |
| suppression 구분 | exception은 fingerprint를 분석 목록에서 숨기고, accepted normal은 계속 노출하되 승인 범위 안에서 anomaly만 억제. 범위 초과 시 breach로 재탐지 |
| 테스트 결과 | Recommendation 테스트에서 정상 통과, 재생성, high-score hard-fail override, invalid JSON fallback을 검증. Accepted Normal 테스트에서 억제, 계속 노출, breach, revoke 및 기존 exception 동작을 검증 |
| 현재 한계 | prompt injection 또는 system prompt 추출 시도를 전용으로 탐지하는 입력 필터와 공격 corpus 테스트는 현재 구현되어 있지 않다. 따라서 해당 공격을 “방어 성공”으로 주장하지 않음 |

## 4. 기타 문제 해결 사례

| 사례 | 문제 및 적용 결과 |
| --- | --- |
| 날짜 범위 오염 방지 | 클라이언트가 여러 system/time range를 보내도 `/analyze`가 요청 `service_name`과 `analysis_date`로 scope를 고정해 다른 서비스·날짜 로그가 섞이지 않도록 처리 |
| 로그가 없는 서비스 | `LogCollectorAgent`가 fallback log를 만들고 assumption에 기록하여 빈 입력으로 graph 전체가 중단되는 것을 방지 |
| stack trace 비활성화 | `scope.filters.disable_stack_traces`가 설정되면 stack trace evidence를 제거해 요청별 데이터 노출 범위를 제어 |
| Known Pattern 오탐 방지 | exact fingerprint뿐 아니라 keyword, similarity, level scope, stack token, frequency를 점수화하며, 단순 embedding 유사도만으로 Known Pattern을 확정하지 않음 |
| volatile 값 정규화 | UUID, timestamp, duration, IP, request/user ID, URL/path, JSON 값, 숫자를 placeholder로 일반화해 같은 장애가 여러 fingerprint로 분산되는 현상을 완화 |
| duplicate 승인/거절 | 후보 승인 시 normalization rule과 canonical fingerprint alias를 저장하고, 거절 시 candidate 상태를 남겨 동일 후보의 반복 노출을 제어 |
| RAG provider 장애 | embedding key가 없거나 v2 query가 실패하면 legacy Chroma collection 또는 Drain3 기반 결과로 fallback하여 기본 분석을 유지 |
| partial batch failure | embedding batch 전체를 폐기하지 않고 반으로 나누어 재시도하여 정상 document는 저장하고 최종 실패 item만 `v2_failed`에 기록 |
| 최종 결과 보존 | scenario pipeline이 기존 `final` 구조를 덮어쓰지 않고 evidence bundle만 보강하는 회귀 테스트로 Recommendation 결과 유실을 방지 |
| 관측성 | Agent/node 실행 시간과 시작·완료·재시도·실패 상태를 LangSmith 또는 local trace buffer에 기록하고, 분석 진행 상태는 SSE로 전달 |
| 테스트 경고 | 대표 회귀 테스트는 통과했지만 `datetime.utcnow()` 및 TestClient/httpx deprecation warning이 남아 있어 timezone-aware datetime과 test dependency 호환성 정리가 필요 |

## 1. 최종 아키텍처 요약

- **완성된 아키텍처 핵심:** FastAPI를 진입점으로 LangGraph `StateGraph`와 `OrchestratorAgent`가 로그 수집, 패턴 분석, 이상 탐지 Agent를 조건부 라우팅하고, PatternOps/SkillOps runner가 scope별 세부 skill을 실행하는 deterministic-first 멀티 에이전트 분석 파이프라인을 완성했다. 분석 이후에는 SQLite 기반 scenario detection과 ChromaDB RAG를 결합해 fingerprint, Known/New Pattern, anomaly, risk, semantic cluster, time window, system state vector 및 trajectory evidence를 통합하며, 사용자가 선택한 fingerprint에 한해 OpenAI 기반 Recommendation 생성과 품질 게이트를 실행한다.

- **최종 산출물 형태:** Vue 3 + TypeScript 대시보드와 연동되는 FastAPI 기반 장애 예방 AIOps 백엔드다. 기본 분석 결과는 `POST /analyze`의 구조화된 `SharedState` JSON과 SSE 진행 이벤트로 제공하고, 선택 fingerprint의 상세 권고는 `POST /recommendations/fingerprint`에서 preview 형태로 반환한다. 승인된 정상 패턴, Known Pattern, 해결 결과 및 사용자가 명시적으로 저장한 권고는 운영 피드백 데이터로 축적된다.

- **Agent 구조:** 요청은 `FastAPI → SharedState 초기화 → OrchestratorAgent → LogCollectorAgent → LogAnalysisAgent → AnomalyDetectionAgent → deterministic scenario pipeline → KnowledgeBaseRAGAgent → 응답` 순으로 처리된다. `LogCollectorAgent`는 SQLite 로그를 수집하고, `LogAnalysisAgent`는 정규화·fingerprint·Known/New Pattern·PatternOps match를 생성하며, `AnomalyDetectionAgent`는 suppression과 accepted-normal 기준을 반영해 이상 징후를 판정한다. `KnowledgeBaseRAGAgent`는 ChromaDB에서 유사 분석과 Knowledge Card를 검색한다. `RecommendationAgent`는 기본 흐름에서 분리되어 선택 fingerprint 요청에서만 OpenAI를 호출하고, JSON schema와 80점 품질 게이트 및 hard-fail을 거쳐 권고를 생성한다. 구조화 운영 데이터는 현재 SQLite에 저장하고, vector 지식은 ChromaDB에 저장하며, 실행 추적은 LangSmith 또는 local trace buffer와 SSE를 사용한다.

```text
Vue Dashboard / API Client
          │
          ▼
FastAPI (/analyze, /recommendations/fingerprint, feedback APIs)
          │
          ▼
SharedState + LangGraph Orchestrator
          │
          ├─ LogCollectorAgent ───────────────► SQLite service logs
          ├─ LogAnalysisAgent ────────────────► PatternOps / fingerprint registry
          └─ AnomalyDetectionAgent ───────────► suppression / accepted-normal rules
          │
          ▼
Deterministic Scenario Pipeline
  └─ risk / cluster / time window / state vector / trajectory
          │
          ▼
KnowledgeBaseRAGAgent ────────────────────────► ChromaDB / Knowledge Cards
          │
          ├─ 기본 분석 응답: evidence 중심 SharedState
          │
          └─ fingerprint 선택
                    │
                    ▼
             RecommendationAgent ────────────► OpenAI Responses API
                    │
                    ▼
             JSON 검증 + 품질 게이트
                    │
                    ▼
             상세 권고 Preview / 명시적 저장
```
