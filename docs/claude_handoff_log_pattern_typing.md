# Claude Handoff: Log Pattern Typing / Trajectory Clustering

작성일: 2026-07-10

이 문서는 현재 `log_detect_agents` 작업물을 Claude에게 전달하기 위한 인계 문서이다. 목적은 현재 구현 상태를 빠르게 파악하고, 앞으로의 agent 목적성을 `raw log -> template/entity normalization -> event embedding -> time-window state vector -> trajectory construction -> trajectory clustering -> incident pattern catalog` 설계로 정렬하는 것이다.

## 1. 프로젝트 목적

본 프로젝트는 FastAPI + LangGraph 스타일의 멀티 에이전트 구조로 서비스 로그를 수집/정규화하고, 장애 징후를 탐지하며, fingerprint/known pattern/semantic cluster/trajectory cluster/RAG 근거를 활용해 대응 권고안을 만드는 AIOps PoC이다.

현재 구현의 중심은 다음이다.

- 서비스 로그 수집 및 정규화
- fingerprint 생성 및 Known/New Pattern 판정
- duplicate fingerprint 후보 탐지 및 병합
- semantic log cluster 생성
- time-window 기반 system state vector 및 trajectory cluster 생성
- PatternOps/SkillOps 스타일의 skill graph 실행 추적
- Knowledge Card/RAG 기반 추천 생성
- Recommendation 품질 게이트
- Vue 대시보드에서 분석 결과, pattern cluster, trajectory, skill activity 표시

## 2. 앞으로의 설계 목적성

첨부된 설계 가이드 기준으로 agent의 장기 목표는 단순 로그 분석이 아니라 **로그 오류 패턴 유형화**이다.

권장 흐름은 다음이다.

```text
raw log
-> template / entity-type normalization
-> event embedding
-> time-window state vector
-> trajectory construction
-> trajectory clustering
-> incident pattern catalog
-> optional flow matching / transition model
```

핵심 구분은 다음과 같다.

| 단계 | 의미 | 현재 구현 상태 |
| --- | --- | --- |
| Template extraction | raw log에서 변동 token을 제거하고 event type을 만든다. | `normalize_log_text`, Drain3/fallback template, fingerprint 생성으로 일부 구현 |
| Entity normalization | service, dependency, entity_type, error_code, parameter를 구조화한다. | service/log_level/message 중심이며 dependency/entity 추출은 약함 |
| Event embedding | 정규화된 event/template을 벡터화한다. | ChromaDB pattern embedding 및 hybrid similarity 일부 구현 |
| Window vector | 시간 window별 event count + metric feature를 만든다. | `time-window state vector` 및 10차원 feature 일부 구현 |
| Trajectory construction | window vector sequence를 만든다. | trajectory modeling 데이터 생성 구현 |
| Trajectory clustering | 장애 진행 경로를 cluster로 묶는다. | HDBSCAN + signature fallback 구현 |
| Incident pattern catalog | cluster를 운영자가 이해 가능한 장애 유형으로 축적한다. | PatternOps/Knowledge Card 기반은 있으나 catalog schema는 미완성 |
| Flow matching | 현재 상태가 어떤 incident 방향으로 전이되는지 예측한다. | 아직 미구현. trajectory catalog 이후 단계 |

중요한 방향성은 **raw log text를 직접 clustering하지 않고, template/entity/event/window/trajectory로 단계적으로 구조화한 뒤 cluster/catalog를 만든다**는 점이다.

## 3. 현재 아키텍처 요약

### Backend

- 위치: `LOG_DETECT_AGENTS_BACK`
- API: FastAPI
- workflow: LangGraph `StateGraph` 스타일
- state: `app/state.py`의 `SharedState`
- 주요 DB: SQLite `data/logs.db`
- vector store: ChromaDB
- LLM: OpenAI API
- embedding: OpenAI 또는 Azure OpenAI embedding option

기본 분석 흐름은 다음이다.

```text
POST /analyze
-> create_initial_state
-> OrchestratorAgent
-> LogCollectorAgent
-> LogAnalysisAgent
-> AnomalyDetectionAgent
-> run_detection_pipeline
-> PatternOps skill plan refresh
-> KnowledgeBaseRAGAgent
-> AnalyzeResponse
```

상세 추천은 기본 `/analyze`에서 자동 실행되지 않고, 사용자가 fingerprint를 선택해 아래 API를 호출할 때 실행된다.

```text
POST /recommendations/fingerprint
-> RecommendationAgent
-> recommendation_generation
-> recommendation_quality_gate
```

### Frontend

- 위치: `LOG_DETECT_AGENT_FRONT`
- Vue 기반 대시보드
- 주요 화면:
  - `LogDetectDashboard.vue`
  - `SkillOpsDashboard.vue`
  - `TrajectoryDashboard.vue`
- 주요 컴포넌트:
  - `PatternClusterTable.vue`
  - `TrajectoryModelingPanel.vue`
  - `SkillActivityStreamPanel.vue`
  - `RecommendationHistoryPanel.vue`

## 4. Agent별 현재 역할

| Agent | 현재 역할 | 설계 목표 기준 보완 방향 |
| --- | --- | --- |
| `LogCollectorAgent` | SQLite에서 service log를 조회하고 `normalized_logs`, `stack_traces`를 만든다. | fallback 로그 생성을 제거하고, 실제 raw log source에 대한 명확한 empty-state 처리가 필요 |
| `LogAnalysisAgent` | message normalization, fingerprint 생성, known pattern matching, new pattern candidate 생성 | template_id, canonical_event_id, entity binding을 명시 필드로 분리 |
| `AnomalyDetectionAgent` | suppressed log 제외 후 증가/감소/부재/신규 패턴 anomaly 산출 | anomaly를 window-level signal candidate로 승격 |
| `KnowledgeBaseRAGAgent` | 최종 분석 및 승인된 Knowledge Card를 ChromaDB에 저장/조회 | incident pattern catalog와 Knowledge Card의 경계를 분리 |
| `RecommendationAgent` | fingerprint 선택 시 evidence bundle 기반 추천 생성 및 품질 검증 | fallback recommendation 의존을 줄이고 catalog/trajectory 근거 중심 추천으로 전환 |
| `PatternRuleSuggestionAgent` | sample message에서 regex/template rule 제안 | 운영자 승인 기반 template canonicalization workflow로 확장 |
| `OrchestratorAgent` | runnable agent 및 skill plan 선택 | template/event/window/trajectory 단계별 agent routing으로 재정렬 |

상위 기획에는 Impact Evaluation Agent와 Source Code Analysis Agent가 있으나, 현재 활성 API 흐름에서는 독립 agent로 강하게 실행되지 않는다. 현재는 risk/rationale, `source_code_evidence` 필드가 recommendation context에 포함되는 수준이다.

## 5. 이번 주 핵심 변경 요약

`main` 기준 2026-07-06 ~ 2026-07-10에 반영된 핵심 작업은 다음이다.

- PatternOps/SkillOps 실행 그래프 및 validator 결과 표시 강화
- pattern cluster 생성 및 화면 표시 추가
- semantic log cluster 저장 및 추천 근거 매칭 개선
- trajectory modeling 데이터 생성 및 대시보드 표시 추가
- SSE 기반 skill activity stream 추가
- ChromaDB v2 pattern/template/known/case/incident 컬렉션 분리
- duplicate pattern 후보, manual merge, pattern rule 승인 UX 개선
- Recommendation 품질 게이트 및 evidence bundle 강화
- `scikit-learn>=1.3` 추가 및 cosine distance 기반 semantic clustering 개선

순수 변경 범위는 대략 49개 파일이며, 주요 변경 파일은 다음이다.

- `LOG_DETECT_AGENTS_BACK/app/main.py`
- `LOG_DETECT_AGENTS_BACK/app/db/scenario_store.py`
- `LOG_DETECT_AGENTS_BACK/app/db/chroma_store.py`
- `LOG_DETECT_AGENTS_BACK/app/agents/recommendation.py`
- `LOG_DETECT_AGENTS_BACK/app/patternops/runner.py`
- `LOG_DETECT_AGENTS_BACK/app/patternops/skill_graph.py`
- `LOG_DETECT_AGENTS_BACK/app/patternops/validators.py`
- `LOG_DETECT_AGENTS_BACK/app/streaming.py`
- `LOG_DETECT_AGENT_FRONT/src/stores/logDetectStore.ts`
- `LOG_DETECT_AGENT_FRONT/src/types/agentTypes.ts`
- `LOG_DETECT_AGENT_FRONT/src/components/dashboard/PatternClusterTable.vue`
- `LOG_DETECT_AGENT_FRONT/src/components/dashboard/TrajectoryModelingPanel.vue`
- `LOG_DETECT_AGENT_FRONT/src/components/dashboard/SkillActivityStreamPanel.vue`

## 6. 현재 데이터 모델/산출물

현재 `SharedState.evidence`에 들어가는 주요 산출물은 다음이다.

| 산출물 | 의미 |
| --- | --- |
| `normalized_logs` | LogCollector/LogAnalysis가 정규화한 로그 |
| `stack_traces` | stack trace evidence |
| `known_pattern_matches` | DB/config/PatternOps 기반 known pattern match |
| `new_pattern_candidates` | 신규 패턴 후보 |
| `duplicate_pattern_candidates` | 병합 후보 fingerprint group |
| `clusters` | fingerprint 중심 cluster rows |
| `pattern_clusters` | semantic/pattern cluster 요약 |
| `semantic_clusters` | semantic log cluster |
| `fingerprint_merge_groups` | canonical fingerprint 병합 근거 |
| `trajectory_event_windows` | 시간 window event aggregation |
| `trajectory_state_vectors` | window-level state vector |
| `trajectory_clusters` | trajectory clustering 결과 |
| `nearest_trajectory_patterns` | 현재 trajectory와 가까운 과거 pattern |
| `pattern_ops_skill_plan` | 선택된 PatternOps skill plan |
| `pattern_ops_skill_executions` | skill 실행 결과 |
| `pattern_ops_validator_results` | validator 결과 |
| `recommendation_evidence_bundle` | 추천 생성 근거 bundle |

설계 목표와 비교하면 `template_id`, `canonical_event_id`, `dependency`, `entity_type`, `entity_id`, `error_code`, `parameter_values` 같은 event ontology 필드가 아직 약하다.

## 7. Fallback/Stub 정리 대상

현재 코드에는 PoC 연속 실행을 위해 fallback이 많이 남아 있다. Claude가 이어받을 때 우선 정리해야 할 대상이다.

| 우선순위 | Fallback | 현재 동작 | 정리 방향 |
| --- | --- | --- | --- |
| High | LogCollector fallback logs | DB 로그가 없으면 synthetic log 10건 생성 | 운영 모드에서는 제거. 빈 로그는 empty result/error로 처리 |
| High | `LLM_STUB_MODE=true` 기본값 | env 미설정 시 stub mode 활성 | 기본값 false 또는 profile별 명시 설정 |
| High | fallback recommendation validator success | `quality_gate_status=fallback`이면 validator 통과 | fallback은 성공이 아니라 degraded result로 분리 |
| High | Recommendation fallback | LLM/RAG 실패 시 기본 권고안 생성 | UI에 명확히 표시하고 저장/Knowledge Card 승인 차단 |
| Medium | Drain3 fallback template | Drain3 미설치 시 regex template 사용 | fallback이 아니라 deterministic baseline parser로 격상하거나 의존성 명시 |
| Medium | semantic cluster fallback | embedding/HDBSCAN 실패 시 Drain template grouping | algorithm/source/confidence를 결과에 명확히 노출 |
| Medium | trajectory fallback | HDBSCAN 실패 시 signature grouping | baseline algorithm으로 이름을 정리하고 threshold 문서화 |
| Medium | Chroma v2 -> v1 fallback | v2 결과 없으면 legacy collection 조회 | migration 완료 후 제거하거나 compatibility layer로 격리 |
| Low | LangSmith local fallback | tracing off/API 실패 시 local events 반환 | 운영 trace와 local trace source 구분 유지 |
| Low | Frontend local progress | SSE 이벤트 전 local-stage progress 표시 | 실제 backend event와 혼동되지 않도록 UI label 유지 |

중요한 점은 “fallback으로라도 계속 돌아가게 하기”가 초기 PoC에는 유용했지만, 오류 패턴 유형화 모델을 만들려면 fallback 데이터가 training/catalog에 섞이면 안 된다는 것이다.

## 8. 설계 목표 대비 Gap

| 영역 | 현재 상태 | Gap |
| --- | --- | --- |
| Template extraction | regex normalization + Drain3/fallback | template_id/canonical_event_id가 명시 schema로 고정되지 않음 |
| Entity binding | service/log_level/message 중심 | dependency, endpoint, region, entity_type, error_code 추출 부족 |
| Event embedding | Chroma text embedding 중심 | categorical/numeric/topology feature 결합 부족 |
| Window vector | state vector 일부 구현 | feature registry와 schema version 관리 필요 |
| Trajectory clustering | HDBSCAN + fallback signature | DTW/edit distance/motif mining 미구현 |
| Incident catalog | Knowledge Card/PatternOps 일부 | incident pattern catalog 독립 schema 필요 |
| Prediction | nearest trajectory pattern 수준 | flow matching/transition model 미구현 |
| Evaluation | pytest 일부 존재 | cluster 품질, catalog purity, fallback contamination 검증 부족 |

## 9. Claude에게 제안하는 다음 작업 순서

### 1단계: fallback 제거/격리

- `LogCollectorAgent`의 synthetic fallback log 제거 또는 dev-only flag로 제한
- `LLM_STUB_MODE` 기본값 재검토
- fallback recommendation을 `success`가 아닌 `degraded`로 모델링
- fallback 산출물이 ChromaDB/Knowledge Card/catalog에 저장되지 않도록 guard 추가

### 2단계: event ontology schema 도입

`normalized_logs`에 아래 필드를 추가하는 방향이 좋다.

```json
{
  "event_id": "evt_...",
  "template_id": "dependency_timeout",
  "canonical_event_id": "redis_timeout",
  "template_text": "connection to <*> timed out after <DURATION>",
  "service": "checkout-api",
  "dependency": "redis",
  "severity": "ERROR",
  "entity_type": "dependency",
  "entity_id": "redis",
  "error_code": "ETIMEDOUT",
  "parameter_values": {
    "duration_ms": 5000
  }
}
```

### 3단계: window vector schema 고정

`trajectory_state_vectors`에 schema version과 feature registry를 붙인다.

```json
{
  "schema_version": "window-vector-v1",
  "window_start": "2026-06-26T10:00:00",
  "service": "checkout-api",
  "event_counts": {
    "redis_timeout": 42
  },
  "metrics": {
    "latency_p95": 1850,
    "error_rate": 0.07
  },
  "topology": {
    "dependency": "redis"
  }
}
```

### 4단계: trajectory clustering baseline 정리

초기 ROI가 높은 baseline은 다음이다.

```text
template/entity normalization
-> 5min window count vector
-> HDBSCAN
-> LLM/operator label
-> incident pattern catalog
```

이후 DTW/hierarchical clustering, edit distance/LCS, motif mining을 추가한다.

### 5단계: incident pattern catalog 분리

Knowledge Card는 해결 사례이고, incident pattern catalog는 장애 유형이다. 둘을 분리하는 것이 좋다.

권장 catalog record:

```json
{
  "pattern_id": "INC_PATTERN_007",
  "label": "Redis timeout induced retry storm",
  "signature": [
    "redis_timeout ↑",
    "retry_exceeded ↑",
    "db_pool_wait ↑",
    "api_5xx ↑"
  ],
  "common_services": ["checkout-api", "cart-api"],
  "typical_duration_min": 35,
  "severity_distribution": {
    "P1": 2,
    "P2": 9,
    "P3": 31
  },
  "recommended_actions": [],
  "linked_knowledge_cards": []
}
```

### 6단계: flow matching은 후순위

Flow matching은 clustering 알고리즘이 아니라 상태 전이/생성 모델이다. 현재 단계에서는 먼저 trajectory clustering으로 incident pattern catalog를 안정화하고, 충분한 historical trajectory와 label이 쌓인 뒤에 transition model로 확장하는 것이 맞다.

## 10. 주요 파일 지도

| 파일 | 역할 |
| --- | --- |
| `LOG_DETECT_AGENTS_BACK/app/main.py` | FastAPI endpoint, analyze/recommendation/pattern API orchestration |
| `LOG_DETECT_AGENTS_BACK/app/state.py` | `SharedState` schema |
| `LOG_DETECT_AGENTS_BACK/app/graph/*` | LangGraph workflow 구성 |
| `LOG_DETECT_AGENTS_BACK/app/agents/log_collector.py` | 로그 수집 |
| `LOG_DETECT_AGENTS_BACK/app/agents/log_analysis.py` | normalization/fingerprint/known-new 판정 |
| `LOG_DETECT_AGENTS_BACK/app/agents/anomaly_detection.py` | anomaly detection |
| `LOG_DETECT_AGENTS_BACK/app/agents/recommendation.py` | recommendation + quality gate |
| `LOG_DETECT_AGENTS_BACK/app/agents/pattern_rule_suggestion.py` | pattern rule suggestion |
| `LOG_DETECT_AGENTS_BACK/app/db/scenario_store.py` | detection pipeline, fingerprint, semantic cluster, trajectory modeling |
| `LOG_DETECT_AGENTS_BACK/app/db/chroma_store.py` | ChromaDB collection, embedding, similarity search |
| `LOG_DETECT_AGENTS_BACK/app/patternops/*` | PatternOps registry, skill graph, runner, validators |
| `LOG_DETECT_AGENTS_BACK/app/streaming.py` | SSE event stream |
| `LOG_DETECT_AGENT_FRONT/src/stores/logDetectStore.ts` | frontend state/action orchestration |
| `LOG_DETECT_AGENT_FRONT/src/types/agentTypes.ts` | frontend API/shared types |
| `LOG_DETECT_AGENT_FRONT/src/components/dashboard/PatternClusterTable.vue` | pattern/fingerprint cluster UI |
| `LOG_DETECT_AGENT_FRONT/src/components/dashboard/TrajectoryModelingPanel.vue` | trajectory modeling UI |
| `LOG_DETECT_AGENT_FRONT/src/components/dashboard/SkillActivityStreamPanel.vue` | skill execution stream UI |

## 11. 테스트/검증 포인트

기존 테스트에서 참고할 만한 영역은 다음이다.

- `tests/test_scenario_fingerprints.py`
  - fingerprint normalization
  - duplicate candidate detection
  - semantic log cluster
  - trajectory/state vector 관련 검증
- `tests/test_pattern_cluster_chroma.py`
  - ChromaDB v2 collection
  - embedding query fallback
  - similar pattern retrieval
- `tests/test_recommendation_agent.py`
  - recommendation quality gate
  - fallback recommendation behavior
- `tests/test_health.py`
  - recommendation/knowledge card/exception API

추가로 필요한 테스트는 다음이다.

- fallback log가 운영 mode에서 생성되지 않는지
- fallback recommendation이 Knowledge Card로 저장되지 않는지
- event ontology 필드가 누락되지 않는지
- window vector schema version이 유지되는지
- trajectory cluster algorithm/source/confidence가 응답에 노출되는지
- incident pattern catalog가 Knowledge Card와 분리 저장되는지

## 12. Claude에게 전달할 핵심 판단

이 프로젝트는 현재 기능이 꽤 많이 붙어 있지만, 아직 PoC 성격의 fallback과 compatibility path가 섞여 있다. 다음 단계의 핵심은 기능 추가보다 **데이터 의미론을 정리하는 것**이다.

가장 중요한 리팩터링 축은 다음이다.

1. synthetic/fallback 산출물이 실제 분석 데이터처럼 저장되는 경로 차단
2. `message/fingerprint` 중심 모델에서 `template_id/canonical_event_id/entity/window/trajectory` 중심 모델로 전환
3. Knowledge Card, Known Pattern, PatternOps Contract, Incident Pattern Catalog의 역할 분리
4. trajectory clustering을 본체로 삼고 flow matching은 후속 예측 모델로 보류

Claude가 이어받을 때는 먼저 fallback 정리와 schema 경계 정리부터 진행하는 것이 좋다.

