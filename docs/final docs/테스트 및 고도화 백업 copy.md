## **주요 문제 해결 및 기술 리서치 (테스트 단계)**

| **이슈 구분**         | **문제 상황 및 원인**                                                                                             | **리서치 및 해결 과정 (Reference & Solution)**                                                                                                                                                                                                                                               |
| ----------------- | ---------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **품질/환각**         | LLM evaluator가 높은 점수를 주더라도 원인 근거, action 세부 필드, 검증 및 예방 단계가 빠진 답변이 통과할 수 있었다.                              | • **리서치:** evaluator 점수만 사용하는 방식의 한계를 확인하고 structured output, deterministic validation, test-time regeneration 조합을 검토 • **적용:** evaluator와 별개로 `_hard_fail_reasons()`를 실행해 evidence 연결, action 필드, 검증 2개 이상, 예방 단계, 금지 조치를 검사. 테스트에서는 evaluator가 92점을 준 불완전 답변도 거절하고 재생성된 84점 답변을 채택 |
| **출력 파싱**         | OpenAI 응답이 JSON이 아니거나 필수 구조를 만족하지 않으면 Recommendation workflow 전체가 실패할 수 있었다.                               | • **리서치:** schema-constrained prompt와 parser 실패 시 graceful degradation 방식 검토 • **적용:** JSON object 단일 출력 지시, custom parser/validator, 최대 3회 재시도 후 deterministic fallback 적용. 연속 `not-json` 응답 테스트에서 `recommendation_source="fallback"`으로 정상 종료                                       |
| **검색 정확도**        | embedding similarity만 높고 message 구조가 다른 로그가 동일 패턴이나 duplicate candidate로 잘못 묶일 수 있었다.                      | • **리서치:** semantic similarity와 lexical/structural evidence를 결합하는 hybrid matching 검토 • **적용:** token, 구조, stack trace, metadata, embedding score를 함께 평가하고 pattern similarity가 낮으면 높은 embedding score만으로 Known/duplicate 판정을 덮어쓰지 않도록 제한                                              |
| **임베딩 속도/비용**     | pattern 또는 query마다 embedding API를 개별 호출하면 collection 수와 fingerprint 수에 비례해 호출 횟수가 증가한다.                    | • **리서치:** OpenAI embedding batch input과 Chroma query embedding 재사용 방식 검토 • **적용:** 저장과 검색 모두 batch 처리하고, analysis query embedding은 여러 v2 collection에서 재사용. 이미 존재하는 document ID는 embedding 대상에서 제외하고 batch 실패 시 반으로 분할해 실패 item을 격리                                                  |
| **반복 분석 성능**      | 같은 서비스/날짜/옵션을 다시 분석할 때 정규화, clustering, RAG query를 전부 재실행하는 비용이 발생한다.                                      | • **리서치:** deterministic pipeline 결과 cache와 incremental processing 방식 검토 • **적용:** `_PIPELINE_CACHE`에 결과를 저장하고 반환 시 `deepcopy`하여 호출자 변형을 차단. 신규 raw log만 처리하고, normalization rule·exception·accepted normal·merge 등 결과에 영향을 주는 mutation 시 cache를 clear                               |
| **클러스터 fallback** | embedding API key가 없거나 embedding/HDBSCAN 결과를 만들 수 없으면 semantic cluster가 비어 downstream evidence가 약해질 수 있었다. | • **리서치:** template 기반 deterministic clustering을 fallback으로 사용하는 방식 검토 • **적용:** OpenAI embedding/HDBSCAN을 사용할 수 없을 때 Drain3 template 기반 `drain3_template_fallback` cluster를 생성                                                                                                      |
| **보안/가드레일**       | 생성 권고가 인프라 변경, 임의 DB schema 변경, secret/credential rotation 또는 파괴적 명령을 포함할 가능성이 있다.                         | • **리서치:** prompt-level 정책만으로 차단하지 않고 생성 후 deterministic policy check를 병행하는 방식 검토 • **적용:** prompt 금지 지시 + evaluator safety 항목 + 금지어 hard-fail을 중첩 적용. 권고 이력은 생성 즉시 저장하지 않고 사용자가 `/recommendations/save`를 호출할 때만 저장                                                                  |
| **운영 피드백**        | accepted normal을 exception과 동일하게 숨기면 이후 occurrence 증가를 관측하거나 breach로 재탐지할 수 없다.                            | • **리서치:** suppression과 observable baseline을 분리하는 feedback loop 검토 • **적용:** exception은 분석 목록에서 제외하고 accepted normal은 목록에 유지. 승인 범위 초과 시 `ACCEPTED_NORMAL_BREACH`, revoke 시 기존 anomaly 판정으로 복귀하도록 테스트                                                                                |

## 0. 테스트 재현성 및 범위 요약

### 0.1 분류 기준

| 구분 | 기준 |
| --- | --- |
| **Blocking** | 운영 안정성, 안전성, 사용자 신뢰도에 직접 연결되어 실패 시 배포 판단을 막아야 하는 테스트 |
| **Core** | 품질, 성능, 비용, 데이터 일관성에 영향을 주는 주요 기능 테스트 |
| **Supporting** | 사용성, 관측성, 후속 확장 준비에 가까운 보조 기능 테스트 |
| **검증 완료** | 단위 테스트 또는 고정 fixture로 입력, 기대 결과, 실제 결과를 확인한 항목 |
| **부분 적용** | 코드와 화면 또는 데이터 구조는 반영되었으나 전체 E2E/운영 조건 검증은 아직 제한적인 항목 |
| **향후 확장** | 이번 PoC의 직접 검증 범위가 아니라 후속 모델링 또는 운영화 단계에서 다룰 항목 |

### 0.2 핵심 테스트 케이스 요약

| 중요도 | 적용 상태 | 테스트 대상 | 입력 조건 | 기대 결과 | 실제 결과 | 판정 |
| --- | --- | --- | --- | --- | --- | --- |
| Blocking | 검증 완료 | Recommendation hard-fail | evaluator가 92점을 주지만 필수 action, 검증, 예방 구조가 부족한 답변 | 점수와 무관하게 hard-fail 처리 후 재생성 | 92점 답변을 거절하고 재생성된 84점 답변을 채택 | 통과 |
| Blocking | 검증 완료 | invalid JSON fallback | LLM이 연속으로 `not-json` 응답 반환 | workflow 중단 없이 fallback 권고로 정상 종료 | `recommendation_source="fallback"`, `quality_gate_status="fallback"` 기록 | 통과 |
| Blocking | 검증 완료 | Accepted Normal 억제/노출/breach/revoke | anomaly fingerprint를 정상 기준선으로 승인한 뒤 재분석, 허용 count 초과, revoke 실행 | 목록에는 계속 보이고, 기준 이내에서는 anomaly 제외, 초과 시 breach, revoke 후 기존 판정 복귀 | `accepted_normal_count=1`, 초과 시 `accepted_normal_breach_count=1`, revoke 후 count 0 | 통과 |
| Core | 검증 완료 | embedding batch 및 기존 ID skip | 여러 pattern/query와 이미 저장된 v2 document ID 포함 | embedding 호출을 batch화하고 기존 ID는 저장 대상에서 제외 | batch query는 embedding client 1회 호출, 저장 테스트에서 `v2_skipped=1` 확인 | 통과 |
| Core | 검증 완료 | pipeline cache/incremental 처리 | 동일 서비스/조건으로 pipeline 2회 실행 | 첫 실행만 신규 로그 처리, 재실행은 신규 처리 0건 | `processed_new_logs`가 1에서 0으로 감소 | 통과 |
| Core | 검증 완료 | Time-window 선택 실행 | `include_time_windows=false`로 분석 실행 | time-window/state vector 테이블을 생성하지 않고 빈 결과 반환 | `event_time_windows=[]`, `system_state_vectors=[]`, DB count 0 | 통과 |
| Core | 검증 완료 | Drain3 batch template mining | 로그 메시지 3건을 template mining 대상으로 입력 | row별 miner 생성이 아니라 batch 1회 처리 | batch 호출 1회, batch 내부 메시지 3건 확인 | 통과 |
| Supporting | 부분 적용 | `service_logs_v2` event ontology | redis timeout raw log 1건을 v2 event로 변환 | template, canonical event, dependency, entity, parameter 추출 | `dependency_timeout`, `redis_timeout`, `duration_ms=5000` 추출 확인. 단, 주 pipeline 연계는 후속 범위 | 통과 |

### 0.3 현재 확보한 최소 정량 근거

| 항목 | 관찰 가능한 수치 또는 판정 기준 |
| --- | --- |
| Recommendation 품질 기준 | 총점 80점 이상이면서 hard-fail 사유 0건이어야 통과 |
| 재생성 동작 | 72점 답변은 feedback 반영 후 2회차 84점으로 통과, 최대 재생성 횟수는 3회 |
| 고득점 불완전 답변 차단 | evaluator 92점 답변도 필수 구조 누락 시 hard-fail로 거절 |
| invalid JSON 대응 | 연속 비정형 응답에서도 fallback 상태값 2개(`recommendation_source`, `quality_gate_status`)와 assumption 기록 확인 |
| 기존 ID skip | v2 저장 테스트에서 기존 document 1건을 `v2_skipped=1`로 제외 |
| batch query | 여러 query 또는 여러 collection 검색에서 query embedding을 1회 생성 후 재사용하는 테스트 통과 |
| pipeline incremental | 동일 조건 재실행 시 `processed_new_logs` 1건 → 0건으로 감소 |
| time-window skip | `include_time_windows=false`에서 window/vector 결과 및 DB row count 모두 0 |
| Drain3 batch | 로그 3건을 miner batch 1회로 처리 |
| 대시보드 반환 제한 | time-window 24건, trajectory 12건, trajectory cluster 8건, nearest trajectory 3건으로 반환 상한 설정 |

### 0.4 PoC 범위와 확장 범위

| 항목 | 중요도 | 적용 상태 | 범위 판단 |
| --- | --- | --- | --- |
| Recommendation quality gate 및 hard-fail | Blocking | 검증 완료 | 이번 PoC의 핵심 안정성 범위 |
| JSON parsing fallback | Blocking | 검증 완료 | 이번 PoC의 핵심 안정성 범위 |
| Accepted Normal과 Exception 분리 | Blocking | 검증 완료 | 운영 피드백 반영 범위 |
| batch embedding/query, 기존 ID skip | Core | 검증 완료 | 비용/성능 고도화 범위 |
| pipeline cache와 incremental 처리 | Core | 검증 완료 | 반복 분석 성능 고도화 범위 |
| SSE 실행 상태 표시 | Supporting | 부분 적용 | 화면 관측성 개선 범위. 브라우저 E2E 자동 검증은 후속 보강 필요 |
| pattern/semantic/trajectory evidence 분리 | Supporting | 부분 적용 | 분석 evidence 구조 확장. 모델 예측 정확도 검증은 아님 |
| `service_logs_v2` event ontology | Supporting | 부분 적용 | 변환 함수와 테스트는 있으나 주 pipeline 입력 전환은 후속 범위 |
| RecFM/forecast API/transition model | Core | 향후 확장 | 이번 PoC에서는 미구현이며 trajectory data 축적 이후 검토 |

## 1. LLM 답변 품질 평가 및 개선

| 항목       | 내용                                                                                                                                                          |
| -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 평가 대상 기능 | 선택 fingerprint에 대한 RAG/evidence 기반 상세 권고 생성                                                                                                                 |
| 평가 데이터   | `payment-api` timeout fingerprint, anomaly, risk score, source evidence, Known Pattern, Knowledge Card를 조합한 고정 테스트 fixture. 현재 별도 Ground Truth 30건 데이터셋은 없음 |
| 평가 방식    | LLM evaluator의 100점 rubric과 deterministic hard-fail을 함께 사용. RCA 근거 25점, action 실행 가능성 25점, 검증 20점, 예방 15점, 안전성 15점                                          |
| 통과 기준    | 총점 80점 이상이면서 hard-fail 사유가 없어야 함                                                                                                                            |
| 초기 문제    | 약한 권고가 72점으로 기준 미달하거나, 불완전한 답변이 evaluator에서 92점을 받아도 필수 action/검증/예방 구조가 누락되는 edge case 확인                                                                  |
| 개선 조치    | evaluator feedback을 다음 생성 prompt에 전달하여 최대 3회 재생성하고, `_hard_fail_reasons()`로 점수와 무관한 필수 조건을 강제. evidence bundle에 quality score/status/attempts/feedback을 기록  |
| 개선 후 결과  | 정상 fixture는 86점, 1회차 통과. 72점 답변은 feedback 반영 후 2회차 84점으로 통과. evaluator 92점의 불완전 답변은 hard-fail로 거절하고 다음 84점 답변을 채택                                           |
| 파싱 실패 결과 | 연속 비정형 응답은 예외로 workflow를 중단하지 않고 deterministic fallback으로 전환. `quality_gate_status="fallback"`과 assumption을 기록                                              |
| 현재 한계    | Faithfulness/Relevance를 독립 Ground Truth 데이터셋으로 측정하는 평가 harness는 아직 없음. 현재 수치는 Recommendation rubric fixture 결과이며 RAG 전체 정확도 백분율이 아님                         |

## 2. 성능 및 비용 최적화

| 항목     | 내용                                                                                                                                                                            |
| ------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 기존 병목  | fingerprint별 embedding 저장, query별 collection 반복 embedding, 로그 row마다 Drain3 miner 생성, 동일 조건 pipeline 재실행                                                                       |
| 개선 전략  | batch embedding/query, query embedding 재사용, 기존 ID skip, batch 실패 분할, miner batch 재사용, pipeline result cache, 신규 raw log incremental 처리                                        |
| 적용 기술  | OpenAI/Azure OpenAI Embeddings batch input, ChromaDB batch upsert/query, `_PIPELINE_CACHE`, `functools.lru_cache`, `copy.deepcopy`, Drain3 batch template mining              |
| 검색 최적화 | `find_similar_pattern_clusters_batch()`는 query 목록을 한 번에 embedding하고, `find_similar_analysis_documents_batch()`는 생성한 query embedding을 case/known/incident collection에 재사용      |
| 저장 최적화 | v2 collection의 기존 ID를 먼저 확인해 이미 저장된 문서는 embedding과 upsert를 건너뜀. 실패 batch는 재귀적으로 나눠 정상 item 저장을 계속하고 실패 item만 기록                                                               |
| 분석 최적화 | 동일 cache key는 pipeline 결과 복사본을 반환하며, 재실행 시 신규 raw log만 처리한 수를 metrics로 추적. `include_time_windows=false`, `include_similar_clusters=false`로 선택적 고비용 분석 생략 가능                   |
| 테스트 결과 | batch query가 여러 query에 대해 embedding client를 한 번 호출하는지, analysis query embedding을 여러 collection에서 재사용하는지, Drain3 miner가 로그 row별이 아닌 한 batch로 실행되는지, 기존 ID가 skip되는지를 단위 테스트로 검증 |
| 정량 결과  | 현재 저장소에는 최적화 전후 latency·token·API 비용을 동일 조건으로 측정한 benchmark 결과가 없어 “몇 초 단축” 또는 “몇 % 절감” 수치는 제시하지 않음                                                                           |
| 현재 한계  | cache는 프로세스 메모리 기반으로 worker 간 공유되지 않으며 Redis/Semantic Cache는 사용하지 않음. LangGraph worker와 MCP tool은 현재 동기 순차 실행이며 `asyncio` 병렬 tool calling은 적용되지 않음                            |

## 3. 예외 처리 및 가드레일

| 항목             | 내용                                                                                                                                                               |
| -------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 권고 차단 대상       | 인프라 변경, 임의 DB schema 변경, secret/credential rotation, 파괴적 명령, 구체 evidence 없는 원인 단정, 필수 검증/예방 단계가 없는 조치                                                            |
| 탐지 방식          | Recommendation system prompt의 금지 지시, LLM evaluator safety 점수, 생성 결과의 deterministic `_hard_fail_reasons()` 검사                                                     |
| 입력 검증          | FastAPI/Pydantic 모델로 필수값, 문자열 최소 길이, list 최소 개수와 날짜 타입 등을 검증. MCP registry에 없는 tool name은 `ValueError` 처리                                                        |
| 출력 검증          | JSON object parsing, action 필수 key 검사, verification 최소 2개, prevention 존재 여부, evidence anchor와 금지어 검사                                                             |
| 대응 로직          | 품질 미달 시 evaluator feedback을 포함해 최대 3회 재생성. 계속 실패하면 최고 점수 결과를 `best_effort`로 반환하고, 생성/파싱 자체가 불가능하면 안전한 fallback 반환                                                |
| Agent 오류 처리    | graph node는 한 번 재시도하고 최종 실패를 `decisions.failures`와 `skipped_agents`에 기록한 뒤 전체 분석을 계속하는 graceful degradation 적용                                                   |
| 데이터 보호         | 권고 preview는 자동 저장하지 않는다. `/recommendations/save`와 `/approvals` 같은 명시적 사용자 동작에서만 추천 이력 또는 승인 지식을 저장                                                               |
| suppression 구분 | exception은 fingerprint를 분석 목록에서 숨기고, accepted normal은 계속 노출하되 승인 범위 안에서 anomaly만 억제. 범위 초과 시 breach로 재탐지                                                         |
| 테스트 결과         | Recommendation 테스트에서 정상 통과, 재생성, high-score hard-fail override, invalid JSON fallback을 검증. Accepted Normal 테스트에서 억제, 계속 노출, breach, revoke 및 기존 exception 동작을 검증 |
| 현재 한계          | prompt injection 또는 system prompt 추출 시도를 전용으로 탐지하는 입력 필터와 공격 corpus 테스트는 현재 구현되어 있지 않다. 따라서 해당 공격을 “방어 성공”으로 주장하지 않음                                             |

## 4. 기타 문제 해결 사례

| 중요도 | 적용 상태 | 사례 | 문제 및 적용 결과 |
| --- | --- | --- | --- |
| Supporting | 부분 적용 | SSE 기반 실행 상태 표시 | 프론트가 로컬 타이머만으로 단계를 넘기면 실제 백엔드 진행 상황과 화면 표시가 어긋나 `Time-window/상태 벡터` 단계가 오래 running처럼 보일 수 있었다. `/analyze/stream`과 `stream_id` 기반 SSE를 추가해 backend stage, partial, skill execution, complete/error 이벤트를 수신하도록 개선했고, SSE가 불가능한 경우에만 health polling fallback을 사용하도록 분리했다. 다만 브라우저 E2E 자동 검증은 후속 보강 범위다. |
| Supporting | 부분 적용 | Event/trajectory evidence 고도화 | raw message와 fingerprint 중심 결과만으로는 장애 진행 흐름, 유사 사례, event ontology를 안정적으로 설명하기 어려웠다. `service_logs_v2`와 변환 함수를 추가해 `template_id`, `canonical_event_id`, `dependency`, `entity_type`, `parameter_values` 같은 event 구조를 준비했고, 분석 결과에는 `pattern_clusters`, `semantic_clusters`, `trajectories`, `trajectory_clusters`, `nearest_trajectory_patterns`를 evidence로 분리해 담도록 확장했다. 현재 주 pipeline은 아직 v1 `service_logs` 기반이므로 v2 전환과 forecast 모델은 후속 범위다. |
| Blocking | 검증 완료 | Accepted Normal과 Exception 분리 | 정상으로 승인한 anomaly를 exception처럼 숨기면 이후 발생량 증가나 기준 초과를 관측할 수 없었다. `accepted_normal_patterns`를 별도로 두고, accepted normal은 목록에 계속 노출하되 anomaly count에서만 제외하도록 처리했다. 허용 범위를 넘으면 `ACCEPTED_NORMAL_BREACH`로 다시 탐지하고, revoke/delete 시 기존 anomaly 판정으로 복귀하도록 테스트했다. |
| Core | 부분 적용 | 부분 갱신 API 도입 | duplicate merge나 manual merge 후 전체 분석을 다시 실행해야 화면 row가 최신 fingerprint/canonical 상태를 반영하는 문제가 있었다. 선택 fingerprint 목록만 다시 enrich하는 pattern cluster partial refresh 경로를 추가해 merge 결과 직후 affected row만 갱신할 수 있게 했고, 프론트 store에서 `partial_refresh` 결과를 기존 cluster 목록에 병합하도록 처리했다. 전체 UI 회귀 자동화는 후속 보강 범위다. |
| Supporting | 검증 완료 | 문서/테스트 기준의 한계 명시 | 기능이 PoC fallback과 deterministic baseline에 의존하는 부분이 있는데도 “모델 정확도”처럼 오해될 수 있었다. 문서에 정량 benchmark 부재, Ground Truth 평가 harness 부재, prompt injection corpus 부재, RecFM/forecast 미구현 같은 한계를 명시해 현재 검증 범위를 과장하지 않도록 정리했다. |
