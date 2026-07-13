## 1. 최종 아키텍처 요약

- **완성된 아키텍처 핵심:** FastAPI + LangGraph 기반 Multi-Agent 로그 분석 파이프라인과 PatternOps/RAG/Trajectory evidence를 결합한 AIOps 분석 서비스

- **최종 산출물 형태:** 백엔드 FastAPI 서버와 Vue 대시보드로 구성된 서비스 로그 이상 탐지 및 대응 권고 PoC

- **Agent 구조:** 사용자가 서비스와 분석 날짜를 선택하면 `/analyze` API가 LangGraph workflow를 실행하고, `LogCollectorAgent → LogAnalysisAgent → AnomalyDetectionAgent` 흐름 이후 deterministic scenario pipeline이 fingerprint, anomaly, risk, pattern cluster, semantic cluster, time-window state vector, trajectory evidence를 보강한다. 추천은 기본 분석과 분리되어 사용자가 fingerprint를 선택한 뒤 `RecommendationAgent`가 RAG/Knowledge Card/PatternOps/trajectory 근거를 기반으로 생성한다.

## 2. KPI 달성도 (Plan vs Actual)

| **평가 지표 (KPI)** | **목표 수치** | **실제 달성 수치** | **달성 여부 및 비고** |
| --- | --- | --- | --- |
| **분석 자동화 범위** | 로그 수집, fingerprint, anomaly, recommendation 근거 자동화 | 로그 수집/정규화, fingerprint, Known/New 판정, anomaly, risk, cluster, state vector, trajectory evidence까지 자동 생성 | 목표 달성 |
| **권고 품질 기준** | 품질 평가 80점 이상 | 정상 fixture 86점 통과, 72점 답변은 재생성 후 84점 통과 | 목표 달성 |
| **안전성 검증** | 위험 권고 차단 및 fallback 처리 | high-score hard-fail override, invalid JSON fallback, 금지 조치 hard-fail 적용 | 목표 달성 |
| **반복 분석 최적화** | 동일 조건 재분석 비용 감소 | cache/incremental 처리로 재실행 시 `processed_new_logs` 1건 → 0건 확인 | 부분 달성 |
| **운영 피드백 반영** | 예외/정상 승인 기준 분리 | Exception과 Accepted Normal 분리, breach/revoke 흐름 검증 | 목표 달성 |
| **E2E UI 연계** | 분석 결과 대시보드 표시 | Vue 대시보드에서 summary, anomaly, cluster, trajectory, recommendation history 표시 | 부분 달성: 브라우저 자동 E2E 테스트는 미완료 |

## 3. 창출된 핵심 가치

### 3-1. 비즈니스 가치

- 장애 로그를 수동으로 분류하던 과정을 fingerprint, anomaly, risk, cluster 단위로 자동 구조화했다.

- 반복적으로 발생하는 Known Pattern과 신규 패턴을 구분해 운영자가 우선 확인해야 할 대상을 좁힐 수 있게 했다.

- 승인된 Knowledge Card와 Accepted Normal 흐름을 통해 운영 피드백이 이후 분석 기준에 반영되도록 했다.

- 추천 결과를 자동 저장하지 않고 사용자 승인 이후 저장하도록 하여 검증되지 않은 권고가 지식화되는 위험을 줄였다.

### 3-2. 기술적 가치

- LangGraph 기반 Agent orchestration과 deterministic scenario pipeline을 결합했다.

- ChromaDB 기반 RAG, PatternOps contract, Knowledge Card, semantic cluster를 recommendation evidence로 연결했다.

- evaluator 점수만 신뢰하지 않고 deterministic hard-fail을 추가해 LLM 권고 품질을 통제했다.

- time-window state vector와 fixed-window trajectory clustering 기반을 마련해 향후 장애 진행 경로 모델링으로 확장할 수 있게 했다.

## 4. 운영 및 보안 고려 사항

- **인증 방식:** 현재 PoC 범위에서는 별도 사용자 인증/인가가 본격 구현되지 않았다. 운영 배포 시 API 인증과 사용자별 권한 통제가 필요하다.

- **권한 통제:** 운영 명령 실행, 인프라 변경, 임의 DB schema 변경, secret rotation은 권고 금지 대상으로 분리했다.

- **Injection 대응:** prompt 지시만이 아니라 생성 후 `_hard_fail_reasons()`를 통해 금지 조치, 필수 검증 단계, evidence anchor를 검사한다.

- **장애 대응:** LLM JSON 파싱 실패나 품질 미달 시 workflow를 중단하지 않고 fallback 또는 best-effort 응답으로 graceful degradation한다.

- **데이터 저장 정책:** 추천 preview는 자동 저장하지 않고 `/recommendations/save`, `/approvals` 같은 명시적 사용자 동작에서만 저장한다.

## 5. 회고 및 향후 확장

### 기술적 한계

- 정량 latency, token, API 비용에 대한 전후 benchmark는 아직 없다.

- RAG 전체 정확도를 평가하는 Ground Truth 데이터셋과 faithfulness/relevance 평가 harness는 미구현이다.

- `service_logs_v2` event ontology는 준비되었지만, 주 분석 pipeline은 아직 v1 `service_logs` 기반이다.

- SSE와 프론트 대시보드는 구현되었지만 브라우저 기반 자동 E2E 회귀 테스트는 부족하다.

- RecFM, forecast API, transition model 같은 정식 trajectory 예측 모델은 아직 후속 범위다.

### Next Step

- `service_logs_v2`를 주 분석 pipeline 입력으로 연결하고 event ontology 기반 window feature를 고도화한다.

- 핵심 분석 흐름에 대해 Playwright 기반 브라우저 E2E 테스트를 추가한다.

- recommendation 품질 평가용 Ground Truth fixture를 확장한다.

- latency/API 비용 benchmark를 수집해 최적화 효과를 정량화한다.

- trajectory clustering 결과를 incident pattern catalog와 연결하고, 충분한 label 축적 후 forecast/transition model을 검토한다.