### 핵심 구현 내용

* 이번 PoC에서는 시스템/서비스 로그를 대상으로 **수집 → 정규화 → Fingerprint 생성 → 패턴 분석 → 이상 탐지 → 유사 사례 조회 → 권고 생성**까지 이어지는 멀티 에이전트 기반 분석 흐름을 구현했습니다. FastAPI 백엔드가 API와 저장소 연계를 담당하고, LangGraph는 Agent 실행 순서와 상태 전이를 제어합니다.

* 분석 과정에서 식별된 Fingerprint, Known Pattern, Knowledge Card, 정규화 Rule은 **PatternOps Registry**를 통해 운영 지식으로 관리됩니다. PatternOps는 승인되거나 의미가 확인된 패턴을 `contract` 형태로 저장하며, 각 contract는 매칭 조건, 원인/추천 조치, 산출물, 검증 조건, 적용 한계를 포함합니다. 이를 통해 이후 분석에서는 단순 로그 매칭을 넘어, 기존 운영 지식에 근거한 패턴 판정과 권고 생성을 수행할 수 있습니다.

* 세부 분석 작업은 SkillOps-style skill graph로 표현했습니다. Skill planner는 현재 evidence와 skill 간 의존 관계를 바탕으로 필요한 작업을 선택하고, 실행 결과를 `pattern_ops_skill_plan`, `pattern_ops_skill_executions`, `pattern_ops_validator_results`로 남깁니다.

**1.1 에이전트 워크플로우 (Agent Workflow)**

* **구현 기능:** 서비스 로그 분석 요청의 범위를 초기화하고, 로그 수집 → 정규화/fingerprint 및 패턴 분석 → 이상 탐지를 순차 조율한 뒤 deterministic scenario 분석과 RAG 조회 결과를 하나의 `SharedState`로 통합한다. 사용자가 fingerprint를 선택하면 별도 Recommendation workflow를 실행한다.

* **동작 원리:** `POST /analyze`가 요청별 상태를 생성하면 `OrchestratorAgent`가 전역 SkillOps plan과 `completed_agents`를 확인해 다음 worker를 선택한다. 각 worker는 scope별 skill graph에서 자신에게 연결된 operation을 실행하고 다시 Orchestrator로 복귀한다. 기본 분석 이후 API 레이어가 risk, cluster, time window, state vector, trajectory를 보강한다. 선택 fingerprint 권고에서는 Knowledge Card 검색 → 구조화 권고 생성 → 품질 평가 순으로 처리한다.

* **주요 기술:** FastAPI, LangGraph `StateGraph`, `SharedState`, Orchestrator pattern, PatternOps/SkillOps runner

**1.2 도구(Tool) 및 함수 연동**

* **구현 기능:** SQLite 로그/분석/권고 데이터 조회·저장, ChromaDB 유사 지식 검색·저장, OpenAI 기반 구조화 권고 생성, deterministic detection pipeline 및 패턴 정규화 rule 제안을 연동한다.

* **동작 원리:** 외부 API 입력은 `AnalyzeRequest`, `FingerprintRecommendationRequest`, `ApprovalRequest` 등의 Pydantic 모델로 먼저 검증한다. Agent는 단일 in-process `MCPClient`를 통해 이름 기반 tool을 호출하고, `MCPServer`는 tool별 handler에서 `arguments`를 명시적인 Python 타입으로 변환한 뒤 SQLite/ChromaDB/OpenAI adapter에 전달한다. deterministic pipeline과 `PatternRuleSuggestionAgent`는 애플리케이션 레이어에서 직접 호출한다.

* **주요 기술:** Pydantic request/response model, in-process MCP-style tool registry, SQLite, ChromaDB, OpenAI API wrapper

**1.3 데이터 및 메모리 (RAG & Context)**

* **구현 기능:** 분석 목표, anomaly pattern, fingerprint, Known Pattern 및 승인된 Knowledge Card를 이용해 유사 장애 사례를 검색하고 Recommendation evidence로 제공한다. Pattern template과 장애 진행 trajectory도 별도 분석 증거로 관리한다.

* **동작 원리:** 한 요청 안에서는 `SharedState`가 context를 유지한다. 장기 지식은 SQLite와 ChromaDB에 저장한다. 임베딩 설정이 있으면 pattern은 1024차원, case/knowledge 문서는 1536차원으로 embedding하여 목적별 v2 collection에서 검색하고, 설정이 없거나 결과가 없으면 legacy collection으로 fallback한다. 선택 fingerprint 권고에서는 exact fingerprint Knowledge Card와 semantic 유사 Knowledge Card를 병합한다.

* **주요 기술:** ChromaDB vector search, OpenAI/Azure OpenAI Embeddings, Knowledge Card, PatternOps Registry, request-scoped `SharedState`

### 워크플로우 및 오케스트레이션 (Workflow & Logic)

#### 2.1 처리 로직

본 PoC는 Agentic Workflow 기준으로 **Planning → Execution → Verification → Memory Update** 흐름을 적용했습니다. FastAPI가 API 진입점과 저장소 연계를 담당하고, LangGraph는 `SharedState`를 기반으로 Agent 실행 순서와 상태 전이를 제어합니다.

주요 적용 패턴은 다음과 같습니다.

| 패턴                             | 적용 내용                                                                        |
| ------------------------------ | ---------------------------------------------------------------------------- |
| **Planning / Meta-Controller** | `OrchestratorAgent`가 현재 상태를 보고 다음 Agent를 선택                                  |
| **Multi-Agent**                | 로그 수집, 로그 분석, 이상 탐지, RAG 조회, 권고 생성을 Agent별로 분리                               |
| **Blackboard**                 | 모든 Agent가 `SharedState.evidence`, `decisions`, `final`을 공유                   |
| **Tool Use**                   | SQLite, ChromaDB, OpenAI, PatternOps Registry를 도구처럼 호출                       |
| **PEV**                        | skill 계획 → Agent 실행 → validator/quality gate 검증                              |
| **Reflection Loop**            | 권고 생성 후 품질 평가, 기준 미달 시 최대 3회 재시도                                             |
| **Memory**                     | Known Pattern, Knowledge Card, PatternOps contract, ChromaDB 문서를 재사용 지식으로 활용 |

처리 흐름은 `LogCollectorAgent → LogAnalysisAgent → AnomalyDetectionAgent`를 기본으로 하며, 이후 scenario pipeline, PatternOps skill plan 갱신, KnowledgeBaseRAGAgent가 추가 실행됩니다. 상세 권고는 선택된 fingerprint 기준으로 `RecommendationAgent`가 생성합니다.

PatternOps는 승인된 Known Pattern, Knowledge Card, normalization rule 등을 `contract` 형태로 관리하는 운영 지식 레지스트리입니다.

로그 분석 중 생성된 fingerprint는 PatternOps contract와 비교되어 `pattern_ops_matches`로 기록되며, skill planner는 현재 evidence와 skill graph를 기준으로 필요한 skill을 선택합니다.

### 주요 문제 해결 및 기술 리서치

구현 과정에서 확인한 문제와 실제 코드에 적용한 해결 방법은 다음과 같다.

|             |                                                                                                                           |                                                                                                                                                                    |
| ----------- | ------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **이슈 구분**   | **문제 상황 및 원인**                                                                                                            | **리서치 및 해결 과정 (Reference & Solution)**                                                                                                                             |
| **워크플로우**   | 단순 순차 함수 호출만으로는 Agent별 실행 상태, 조건부 skip, 실패 및 재시도를 일관되게 추적하기 어려웠다.                                                         | • **리서치:** • **적용:**                                                                                                                                               |
| **프롬프트/품질** | LLM 권고가 일반론에 머물거나 근거 없는 원인과 위험한 운영 조치를 포함할 수 있었다.                                                                         | • **리서치:** • **적용:**                                                                                                                                               |
| **도구 연동**   | API 입력과 내부 tool `arguments`의 타입/필수값이 섞이면 런타임 포맷 오류가 발생하기 쉬웠다.                                                             | • **리서치:** • **적용:**                                                                                                                                               |
| **RAG 검색**  | 서로 성격이 다른 Pattern Template, Knowledge Card, Known Pattern, Incident Summary를 한 collection에 넣으면 metadata와 검색 결과가 섞일 수 있었다. | • **리서치:** • **적용:**                                                                                                                                               |
| **임베딩 성능**  | 모든 문서에 큰 embedding 차원을 고정하면 pattern template처럼 짧은 문서에도 저장 공간과 호출 비용이 커진다.                                                 | • **리서치:** • **적용:**                                                                                                                                               |
| **패턴 분산**   | request ID, 숫자, URL, 파일 경로, timestamp 같은 volatile 값 때문에 동일 장애가 여러 fingerprint로 갈라졌다.                                      | • **리서치:** • **적용:**                                                                                                                                               |
| **정상 피드백**  | 운영자가 정상으로 승인한 반복 패턴을 exception처럼 숨기면 관측 가능성이 사라지고, 이후 임계치 초과도 탐지할 수 없었다.                                                  | • **리서치:** • **적용:**                                                                                                                                               |
| **성능/기타**   | 회귀 테스트에서 timezone 없는 `datetime.utcnow()` 사용과 TestClient/httpx 호환성 deprecation warning이 발생한다.                              | • **확인:** 대표 테스트 실행 시 기능 실패 없이 warning 39건 확인 • **후속 조치:** `datetime.now(datetime.UTC)`로 전환하고 Starlette/FastAPI 테스트 client 의존성 호환 범위를 정리할 필요가 있음. 현재 기능 동작에는 영향 없음 |

### 핵심 동작 검증

아래 결과는 2026-07-13에 다음 대표 테스트를 실행해 확인했다.

```text
cd LOG_DETECT_AGENTS_BACK
pytest app/tests/test_graph_e2e.py tests/test_recommendation_agent.py tests/test_accepted_normal_patterns.py -q
11 passed, 39 warnings in 169.18s
```

**[검증 시나리오: 서비스 로그 분석 요청의 Agent 라우팅]**

* **입력:** `service_name="billing-api"`, `goal="payment auth exception risk investigation"`, `save_to_chromadb=false`

* **에이전트 동작:**

1. `create_initial_state(...)`가 요청 단위 `SharedState`를 생성한다.

2. `OrchestratorAgent`가 `LogCollectorAgent`, `LogAnalysisAgent`, `AnomalyDetectionAgent`를 skill plan에 따라 실행한다.

3. deterministic pipeline이 fingerprint, anomaly, risk 및 evidence bundle을 보강한다.

4. `KnowledgeBaseRAGAgent`가 관련 지식을 조회한다.

5. 기본 분석이므로 `RecommendationAgent`는 skip하고 LLM 상세 권고를 생성하지 않는다.

* **최종 결과:** HTTP 200을 반환하고 `AnomalyDetectionAgent`, `KnowledgeBaseRAGAgent`가 `agents_run`에 포함된다. `RecommendationAgent`는 `skipped_agents`에 포함되며, `final.generated_answer=null`, `final.evidence_bundle`은 생성되고 `rag.saved_to_chromadb=false`로 유지된다.

**[검증 시나리오: 선택 fingerprint의 LLM 권고 및 품질 게이트]**

* **입력:** payment provider timeout anomaly, risk score 82, `payment_client.py::PaymentClient.call` source evidence, Knowledge Card `KC-123`이 포함된 선택 fingerprint 상태

* **에이전트 동작:**

1. `knowledge_card_retrieval`이 관련 Knowledge Card와 참조 ID를 evidence에 연결한다.

2. `recommendation_generation`이 원인, 영향, action, 검증 및 예방 단계를 JSON으로 생성한다.

3. `recommendation_quality_gate`가 evidence 연결, 실행 가능성, 검증, 예방, 안전성을 평가한다.

4. 80점 이상이고 hard-fail이 없으면 통과한다. 낮은 품질이면 evaluator feedback을 반영해 재생성한다.

* **최종 결과:** 정상 권고는 `quality_score=86`, `quality_gate_status="passed"`, `quality_attempts=1`로 통과했다. 첫 평가가 72점인 사례는 2회차에 84점으로 통과했고, 잘못된 JSON이 반복된 사례는 `recommendation_source="fallback"`, `quality_gate_status="fallback"`으로 안전하게 종료됐다. 권고는 자동 저장되지 않아 `saved_recommendation_id=null`이다.

**[검증 시나리오: 이상 패턴의 Accepted Normal 편입과 임계치 초과 재탐지]**

* **입력:** `batch-service`에서 과거 일 2건 수준이던 동일 ERROR가 분석일 10건으로 증가한 spike fingerprint

* **에이전트 동작:**

1. 최초 pipeline이 해당 fingerprint를 실제 anomaly로 탐지한다.

2. 운영자가 `register_accepted_normal_pattern(...)`으로 정상 기준선에 편입한다.

3. 재분석 시 fingerprint는 목록에 유지하지만 anomaly 목록과 count에서는 제외한다.

4. 이후 occurrence count가 승인된 `max_allowed_count`를 넘으면 breach로 재평가한다.

* **최종 결과:** 기준 범위 안에서는 `accepted_normal=true`, `anomaly_type="ACCEPTED_NORMAL"`, `accepted_normal_count=1`로 표시된다. 허용 수량을 넘긴 뒤에는 `anomaly_type="ACCEPTED_NORMAL_BREACH"`, `accepted_normal_breach_count=1`이 되고 anomaly 목록에 다시 포함된다. revoke 후에는 정상 편입이 더 이상 적용되지 않는다.
