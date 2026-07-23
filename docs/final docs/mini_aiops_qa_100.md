# Mini AI-Ops 예상 질의응답 100선

프로젝트 개요와 최종 발표 자료를 기준으로 작성한 질의응답입니다. 수치가 실측되지 않은 항목은 답변에서 명시적으로 구분했습니다.

## Agentic Workflow 설계 관련 질문

### q1_1. 왜 로그 분석 workflow를 단일 LLM 호출이 아니라 여러 Agent로 분리했는가?

로그 수집, 정규화·패턴 판정, 이상 탐지, 지식 검색, 권고 생성은 입력과 실패 방식이 서로 다르기 때문이다. 이를 LogCollectorAgent, LogAnalysisAgent, AnomalyDetectionAgent, KnowledgeBaseRAGAgent, RecommendationAgent로 분리하면 각 단계의 책임과 입출력 계약을 명확히 할 수 있고, 특정 단계만 재시도하거나 교체하기도 쉬워진다. 핵심은 모델의 추론 능력보다 운영 파이프라인의 관찰 가능성과 통제 가능성을 우선한 설계다.

### q1_2. OrchestratorAgent는 실제로 어떤 책임을 가지는가?

OrchestratorAgent는 요청 단위 SharedState를 생성하고, 각 Worker Agent의 실행 순서와 조건부 분기, 재시도, 실패 상태 기록을 관리한다. 직접 로그를 분석하거나 권고를 작성하는 역할이 아니라, 어떤 Agent가 언제 실행되고 어떤 결과를 다음 단계에 전달할지를 통제한다. 따라서 업무 로직과 workflow 제어 로직을 분리하는 조정 계층으로 보는 것이 정확하다.

### q1_3. 왜 분석 workflow와 상세 권고 workflow를 분리했는가?

전체 로그에 대해 매번 LLM 권고를 생성하면 비용과 지연이 커지고, 운영자가 관심 없는 fingerprint까지 불필요하게 처리하게 된다. 그래서 1차 workflow는 모든 로그를 결정적으로 분석해 fingerprint, anomaly, risk, cluster, trajectory를 만들고, 2차 workflow는 운영자가 선택한 fingerprint에 대해서만 RAG와 LLM을 사용한다. 이 구조는 고비용 생성 단계를 선택적 on-demand 작업으로 제한한다.

### q1_4. SharedState에는 어떤 정보가 누적되어야 하는가?

SharedState에는 분석 요청 조건, 수집 로그, 정규화 결과, fingerprint, Known/New Pattern 판정, anomaly와 risk, cluster, trajectory evidence, 단계별 상태와 오류가 누적되어야 한다. 상세 권고 workflow에서는 선택 fingerprint, Knowledge Card, PatternOps 근거, 생성 결과와 quality gate 평가도 포함된다. 중요한 점은 Agent 간에 자유 형식 텍스트가 아니라 검증 가능한 구조화 상태를 교환하는 것이다.

### q1_5. LangGraph가 일반적인 함수 호출 체인보다 적합한 이유는 무엇인가?

이 시스템은 조건부 실행, 단계별 실패 처리, 최대 재시도, fallback, 사용자 선택 이후의 별도 workflow가 필요하다. 단순 Chain은 순차 실행에는 적합하지만 상태 기반 분기와 복구 정책을 명시적으로 표현하기 어렵다. LangGraph를 사용하면 각 노드와 전이 조건을 workflow 계약으로 만들고, 실행 결과와 실패 이력을 SharedState에 남길 수 있다.

### q1_6. LogCollectorAgent와 LogAnalysisAgent를 분리한 이유는 무엇인가?

수집은 서비스·날짜·환경별 데이터 접근과 입력 무결성의 문제이고, 분석은 정규화·fingerprint·패턴 판정의 문제다. 둘을 분리하면 로그 소스가 파일, API, 스트림 등으로 바뀌어도 분석 로직은 유지할 수 있다. 반대로 정규화 알고리즘을 바꾸더라도 수집 계층을 수정할 필요가 없다.

### q1_7. AnomalyDetectionAgent가 Known/New Pattern 판정과 별도로 필요한 이유는 무엇인가?

패턴의 등록 여부와 이상 여부는 같은 개념이 아니다. Known Pattern도 평소보다 급증하거나 silence가 발생하면 이상일 수 있고, New Pattern이라도 낮은 중요도의 일회성 로그일 수 있다. 따라서 패턴 정체성 판정과 시간·발생량 기반 anomaly 판정을 분리해야 운영자가 근거를 정확히 해석할 수 있다.

### q1_8. RecommendationAgent는 어떤 입력이 준비된 뒤 실행되어야 하는가?

선택 fingerprint의 대표 로그, 발생량과 시간 분포, risk, Known/New Pattern 상태, anomaly 근거, exact/semantic Knowledge Card, PatternOps contract, trajectory evidence가 준비된 뒤 실행되어야 한다. 이 정보가 없으면 권고가 일반론으로 흐르거나 근거 없는 조치를 제안할 가능성이 높다. 따라서 RecommendationAgent는 앞단 evidence aggregation이 완료된 상태에서만 호출하는 것이 안전하다.

### q1_9. Quality Gate를 Agent workflow 내부에 둔 이유는 무엇인가?

권고 생성 성공과 운영 가능한 권고 생성은 다르기 때문이다. JSON 형식만 맞아도 검증 단계나 예방 조치가 빠질 수 있고, 높은 evaluator 점수를 받아도 필수 안전 조건을 누락할 수 있다. Quality Gate를 workflow의 정식 단계로 두면 생성 결과가 기준을 통과하기 전에는 저장·승인 단계로 이동하지 못하게 할 수 있다.

### q1_10. 최대 3회 재생성 정책은 왜 필요한가?

무제한 재생성은 비용과 지연을 통제할 수 없고, 같은 오류를 반복할 가능성도 있다. 반대로 1회 생성만 허용하면 일시적인 schema 누락이나 불완전한 답변을 교정할 기회를 잃는다. 최대 3회는 evaluator feedback을 반영할 수 있는 제한된 복구 기회를 제공하면서도 workflow가 무한 루프에 빠지는 것을 방지한다.

### q1_11. JSON 파싱 실패 시 workflow 전체를 중단하지 않는 이유는 무엇인가?

권고 생성은 분석 결과를 보강하는 단계이지, 로그 수집과 이상 탐지 결과 자체를 무효화하는 단계가 아니다. LLM이 비정형 응답을 반환했다는 이유로 전체 분석을 실패 처리하면 운영자는 이미 계산된 deterministic evidence도 보지 못하게 된다. 따라서 parser·validator 재시도 후 deterministic fallback으로 안전 종료하는 것이 더 적절하다.

### q1_12. 운영자 승인 전에는 왜 Knowledge Card나 PatternOps 지식을 저장하지 않는가?

모델이 생성한 원인과 조치는 아직 검증되지 않은 가설이기 때문이다. 이를 자동 저장하면 오류가 다음 분석의 근거로 재사용되어 지식 오염이 누적될 수 있다. 명시적 저장·승인 API를 통해 사람의 검토를 통과한 내용만 장기 지식으로 승격시키는 것이 Human-in-the-loop 설계의 핵심이다.

### q1_13. Accepted Normal 등록은 workflow상 어느 시점에 반영되는가?

운영자가 분석 결과를 검토한 뒤 명시적으로 Accepted Normal을 승인했을 때 반영된다. 이후 분석에서는 해당 fingerprint를 목록에서 유지하되 승인 범위 안의 anomaly만 억제한다. 발생량이 승인 threshold를 넘으면 Accepted Normal Breach로 다시 anomaly가 활성화되므로, 승인 이후에도 관측은 계속된다.

### q1_14. Exception과 Accepted Normal을 서로 다른 workflow로 관리해야 하는 이유는 무엇인가?

Exception은 분석 대상에서 제외하는 명시적 예외이고, Accepted Normal은 계속 관측하되 일정 범위 내에서만 이상 판정을 억제하는 상태다. 둘을 동일하게 처리하면 정상 승인 패턴의 발생량 증가를 놓치게 된다. 따라서 제외와 관측 유지라는 서로 다른 운영 의도를 상태 전이에서 분리해야 한다.

### q1_15. 동일 분석 조건에 대한 cache는 Agent workflow에서 어떻게 사용되어야 하는가?

서비스, 날짜 범위, 분석 옵션, 적용 rule·registry 버전이 동일하면 이전 결과를 재사용할 수 있다. 다만 반환 객체는 deepcopy하여 후속 사용자 조작이 cache 원본을 오염시키지 않게 해야 한다. 신규 raw log가 추가된 경우에는 전체 재실행보다 증분 처리 경로로 전환하는 것이 바람직하다.

### q1_16. workflow의 idempotency는 어느 범위에서 보장되는가?

deterministic normalization, 고정 registry 버전, 동일 입력 로그를 사용하는 분석 단계는 재현 가능하게 설계할 수 있다. 반면 LLM 권고 생성은 모델 버전, temperature, retrieval 결과에 따라 달라질 수 있어 완전한 idempotency를 보장하기 어렵다. 따라서 분석 결과는 결정론적으로 고정하고, 생성 결과는 요청·모델·근거·평가 이력을 함께 저장해 재현성을 보완해야 한다.

### q1_17. SSE는 Agent workflow에서 어떤 역할을 하는가?

SSE는 장시간 실행되는 분석의 단계별 진행 상태를 프론트엔드에 전달한다. 사용자는 수집, 정규화, 패턴 판정, 이상 탐지 등 현재 단계를 확인할 수 있고, 실패 시 어느 노드에서 문제가 발생했는지도 알 수 있다. 이는 UX 기능이면서 동시에 workflow 관찰 가능성을 높이는 운영 인터페이스다.

### q1_18. 선택 fingerprint 단위로 권고를 생성하는 설계의 장점은 무엇인가?

운영자가 실제로 검토할 필요가 있는 항목에만 비용을 집중할 수 있고, 권고의 입력 범위를 좁혀 근거 밀도를 높일 수 있다. 또한 fingerprint별 승인·반려·지식화 이력을 독립적으로 관리할 수 있다. 전체 분석 결과와 권고 생성 결과를 분리해 audit하기도 쉽다.

### q1_19. Agent 간 실패 전파는 어떻게 설계해야 하는가?

필수 선행 단계의 실패는 후속 노드를 차단하되, 이미 생성된 결과는 SharedState에 보존해야 한다. 예를 들어 로그 수집 실패는 분석을 중단해야 하지만, RecommendationAgent 실패는 anomaly 결과 조회까지 막아서는 안 된다. 실패를 fatal, recoverable, degraded로 구분하고 각 상태에 재시도·fallback·사용자 메시지를 매핑하는 것이 적절하다.

### q1_20. 이 workflow에서 사람이 반드시 개입해야 하는 핵심 지점은 어디인가?

normalization rule과 fingerprint alias 승인, Known Pattern 등록, Accepted Normal·Exception 처리, 권고 저장·승인, 자동 조치 실행 전 approval gate가 핵심 개입 지점이다. 사람은 모든 로그를 직접 읽는 대신, 시스템이 압축한 후보와 근거를 검토한다. 즉 Human-in-the-loop의 목적은 자동화를 약화시키는 것이 아니라, 장기 지식과 실제 조치에 대한 책임 경계를 명확히 하는 것이다.

## Problem-Solving Strategy 관련 질문

### q2_1. 동일 장애가 여러 fingerprint로 분산되는 문제의 근본 원인은 무엇인가?

request ID, timestamp, 숫자, URL, 파일 경로처럼 매 실행마다 달라지는 volatile 값이 원문에 포함되기 때문이다. 이 값을 그대로 비교하면 구조가 같은 로그도 서로 다른 문자열로 보인다. 따라서 먼저 결정적 정규화로 변동값을 제거하고, 남은 구조를 기준으로 fingerprint를 생성해야 한다.

### q2_2. 왜 정규식만으로 정규화 문제를 해결하지 않았는가?

정규식은 알려진 변동 패턴에는 강하지만 새로운 포맷이나 복합 stack trace 변형을 지속적으로 흡수하기 어렵다. 규칙을 과도하게 일반화하면 서로 다른 로그를 같은 패턴으로 합칠 위험도 있다. 그래서 deterministic rule을 1차 기준으로 두고 Drain3, token·structure·embedding similarity, HDBSCAN을 후보 생성 보조 수단으로 사용한다.

### q2_3. 왜 embedding만으로 fingerprint를 통합하지 않았는가?

embedding은 의미가 비슷한 로그를 찾는 데 유용하지만, 운영상 다른 원인과 조치가 필요한 로그도 의미적으로 가깝게 배치할 수 있다. 특히 구조가 다른 로그를 잘못 병합하면 Known Pattern 판정과 권고가 오염된다. 따라서 embedding은 자동 병합 기준이 아니라 중복 후보를 제시하는 보조 근거로 제한한다.

### q2_4. Drain3는 이 문제에서 어떤 역할을 하는가?

Drain3는 로그 토큰 구조를 기반으로 반복 템플릿을 추출해 변동값이 있는 로그를 공통 template으로 묶는 데 사용된다. deterministic normalization이 놓친 신규 변형을 발견하는 데 도움이 되지만, 최종 canonical fingerprint를 단독으로 결정하지는 않는다. 결과는 hybrid similarity와 운영자 승인과 함께 사용된다.

### q2_5. HDBSCAN을 사용하는 이유는 무엇인가?

로그 군집 수를 미리 정하기 어렵고 noise point가 많은 환경에서는 밀도 기반 군집이 적합하다. HDBSCAN은 서로 다른 밀도의 군집과 비정상 점을 분리할 수 있어 신규 패턴 후보 탐색에 유용하다. 다만 군집 결과는 장애 의미를 확정하는 정답이 아니라 운영자 검토 대상을 압축하는 후보 생성 결과다.

### q2_6. 50개 변형을 1개 fingerprint로 수렴시킨 결과는 무엇을 증명하는가?

해당 테스트 범위에서 변동값과 유사 변형을 동일 canonical fingerprint로 통합할 수 있음을 보여준다. 이는 fingerprint 분산을 98% 축소했다는 성과와 연결된다. 다만 전체 운영 로그 분포에 대한 일반화 성능까지 증명하는 것은 아니므로, 다양한 서비스와 기간을 대상으로 추가 검증이 필요하다.

### q2_7. Known Pattern과 New Pattern은 어떤 기준으로 구분해야 하는가?

정규화된 fingerprint와 canonical alias를 Known Pattern Registry 및 PatternOps contract와 비교해 일치 여부를 판단한다. exact match뿐 아니라 승인된 alias와 허용 변형 규칙을 적용할 수 있다. registry 밖의 미등록 ERROR/WARN이나 기존 패턴 범위를 벗어난 로그는 New Pattern 후보로 표시한다.

### q2_8. 신규 패턴 발견과 이상 탐지는 어떤 순서로 처리하는가?

먼저 로그를 정규화하고 fingerprint를 만든 뒤 Known/New Pattern을 판정한다. 그 다음 발생량 변화, 신규 출현, 감소, silence, time-window state를 분석해 anomaly를 계산한다. 이 순서를 사용하면 패턴 정체성과 시간적 이상성을 혼동하지 않고 각각의 근거를 분리할 수 있다.

### q2_9. risk와 anomaly를 분리해야 하는 이유는 무엇인가?

anomaly는 평소와 다른 정도를 나타내고, risk는 서비스 영향과 긴급도를 나타낸다. 자주 발생하는 Known Pattern도 영향도가 크면 고위험일 수 있고, 통계적으로 희귀한 로그라도 영향이 작으면 낮은 risk일 수 있다. 운영 우선순위를 위해서는 두 축을 별도로 계산하고 함께 보여줘야 한다.

### q2_10. silence를 anomaly로 보는 이유는 무엇인가?

운영 로그에서는 오류 증가뿐 아니라 평소 발생하던 heartbeat, batch 완료, health signal이 갑자기 사라지는 것도 장애 징후일 수 있다. 단순 ERROR 카운트만 보면 이런 부재 신호를 놓친다. 따라서 기대되는 이벤트의 미발생도 time-window 기반 anomaly 후보로 처리한다.

### q2_11. trajectory evidence는 단순 cluster와 무엇이 다른가?

cluster는 유사 로그를 같은 집단으로 묶는 정적 구조이고, trajectory는 시간에 따라 상태와 패턴이 어떻게 전이되는지를 본다. 예를 들어 warning 증가 후 timeout, retry 폭증, service silence로 이어지는 순서를 표현할 수 있다. 장애 진행 경로를 설명하거나 향후 예측 기능으로 확장하려면 trajectory가 필요하다.

### q2_12. 권고 품질을 evaluator 점수만으로 판정하지 않은 이유는 무엇인가?

평가 모델이 전체적으로 높은 점수를 주더라도 최소 2개의 검증 단계, 예방 조치, evidence anchor 같은 필수 요소가 빠질 수 있다. 또한 위험한 명령이나 근거 없는 단정은 총점에 충분히 반영되지 않을 수 있다. 그래서 점수 기준과 deterministic hard-fail을 함께 사용한다.

### q2_13. 90점 이상이라는 기준은 어떤 의미인가?

100점 rubric에서 운영에 필요한 원인 후보, 조치, 검증, 예방, 근거, 안전성을 종합적으로 충족하는 최소 통과선으로 정의한 것이다. 이 프로젝트에서는 92점이지만 필수 구조가 누락된 답변을 hard-fail로 거절하고, 재생성한 94점 답변을 채택했다. 즉 90점은 필요조건이지 충분조건은 아니다.

### q2_14. deterministic fallback에는 어떤 내용이 포함되어야 하는가?

LLM 생성이 반복 실패해도 선택 fingerprint의 핵심 사실, 위험도, 관련 로그, Known/New Pattern 상태, 확인해야 할 기본 점검 절차를 구조화해 제공해야 한다. 확정 원인을 단정하거나 자동 조치를 제안해서는 안 된다. 목적은 화려한 답변이 아니라 workflow를 안전하게 종료하고 운영자가 다음 행동을 취할 수 있게 하는 것이다.

### q2_15. Accepted Normal breach는 어떤 문제를 해결하는가?

정상으로 승인된 패턴이 이후 급증해도 계속 정상으로 억제되는 문제를 해결한다. 승인 당시의 발생량, 비율, 기간 같은 범위를 저장하고 이를 넘으면 다시 anomaly로 탐지한다. 따라서 정상성 승인을 영구 면제권이 아니라 조건부 운영 계약으로 만든다.

### q2_16. revoke 기능이 필요한 이유는 무엇인가?

운영 환경과 서비스 기준은 바뀔 수 있어 과거의 Accepted Normal 또는 Known Pattern 판단이 더 이상 유효하지 않을 수 있다. revoke를 통해 승인 상태를 해제하면 원래 anomaly 판정과 검토 흐름으로 복귀할 수 있다. 이는 잘못된 지식을 삭제하거나 수정할 수 있는 governance 장치다.

### q2_17. RAG Ground Truth fixture가 필요한 이유는 무엇인가?

현재 유사 Knowledge Card 검색이 실제로 올바른 사례를 얼마나 잘 찾는지 정량 근거가 부족하기 때문이다. 대표 query와 정답 카드 집합을 fixture로 만들면 Recall@k, MRR, nDCG, exact/semantic hit rate를 측정할 수 있다. 이후 embedding 모델, chunking, filter, reranker 변경을 회귀 평가할 수 있다.

### q2_18. 왜 실제 운영 시간 절감 KPI는 아직 달성으로 주장하면 안 되는가?

기능 동작과 캐시·증분 처리 여부는 확인됐지만, 동일 업무를 사람이 수행한 시간과 시스템을 사용한 시간을 같은 조건에서 비교한 실측 데이터가 없다. 발표 자료의 30분에서 5분은 추정치로 표시되어 있다. 따라서 현 단계에서는 기술적 가능성은 제시할 수 있지만 운영 효과는 측정 필요 상태다.

### q2_19. Playwright E2E 테스트가 필요한 이유는 무엇인가?

백엔드 API와 개별 Vue 컴포넌트가 정상이어도 실제 브라우저에서 분석 요청, SSE 진행 표시, 결과 선택, 권고 생성, 승인 흐름이 깨질 수 있다. Playwright는 사용자 시나리오 전체를 자동 재현해 프론트·API·상태관리 통합 회귀를 검증한다. 현재 미완료된 UI 신뢰성 KPI를 보완하는 핵심 과제다.

### q2_20. 이 프로젝트의 문제 해결 전략을 한 문장으로 요약하면 무엇인가?

결정적 규칙으로 재현성을 확보하고, 통계·유사도 모델로 후보를 넓히며, LLM은 근거가 준비된 선택 지점에서만 사용하고, 운영자 승인 결과를 다음 분석의 규칙과 지식으로 환류하는 전략이다.

## System-level Design & Trade-off 질문

### q3_1. SQLite를 사용한 설계의 장점과 한계는 무엇인가?

SQLite는 단일 노드 프로토타입에서 배포가 간단하고, 로그·분석·권고·승인 이력을 하나의 파일 기반 DB로 빠르게 관리할 수 있다. 반면 동시 쓰기, 대규모 보존, 다중 서비스 확장, 고가용성에는 한계가 있다. 상용화 단계에서는 PostgreSQL이나 분산 로그 저장소로 이전하되 schema와 repository interface를 유지하는 전략이 적절하다.

### q3_2. ChromaDB를 선택한 이유와 상용 환경의 trade-off는 무엇인가?

ChromaDB는 Knowledge Card와 패턴 벡터 검색을 빠르게 구현하기 쉬워 PoC에 적합하다. 그러나 대규모 데이터, 복제, 백업, 접근 통제, 운영 모니터링 요구가 커지면 관리형 벡터 DB나 PostgreSQL pgvector, Milvus, OpenSearch 같은 대안이 필요할 수 있다. 핵심은 벡터 DB 자체보다 metadata filter와 평가 가능한 retrieval contract를 유지하는 것이다.

### q3_3. deterministic normalization과 ML 기반 유사도를 함께 쓰는 이유는 무엇인가?

deterministic normalization은 재현성과 설명 가능성이 높지만 새로운 변형에 취약하다. ML 기반 유사도는 미지 패턴을 발견하는 데 강하지만 오병합 위험과 비결정성이 있다. 따라서 규칙을 authoritative 기준으로 두고 ML은 후보 생성과 우선순위화에 사용함으로써 두 방식의 장점을 결합한다.

### q3_4. 정확도와 recall 사이의 trade-off는 어떻게 관리하는가?

자동 병합 기준을 보수적으로 두면 잘못된 통합은 줄지만 운영자가 검토할 후보가 늘어난다. 반대로 threshold를 낮추면 recall은 높아지지만 서로 다른 장애를 합칠 수 있다. 이 프로젝트는 다중 근거와 Human approval을 사용해 후보 탐색 단계에서는 recall을 확보하고, registry 반영 단계에서는 precision을 우선한다.

### q3_5. 모든 로그를 embedding하지 않는 이유는 무엇인가?

embedding은 비용과 지연이 발생하고, deterministic fingerprint로 이미 해결되는 로그에는 추가 가치가 작다. 신규·모호한 fingerprint, Knowledge Card 검색, 의미 기반 cluster처럼 필요한 지점에만 선택적으로 적용하는 편이 효율적이다. batch 처리와 query embedding 재사용도 같은 비용 통제 원칙에 따른다.

### q3_6. batch embedding의 시스템적 장점은 무엇인가?

여러 로그나 카드를 한 번에 처리하면 네트워크 왕복과 API overhead를 줄이고 GPU·서비스 처리량을 높일 수 있다. 동일 query embedding을 여러 collection 검색에 재사용하면 중복 계산도 줄어든다. 다만 batch가 너무 크면 지연과 메모리 사용량이 증가하므로 throughput과 응답시간 사이에서 크기를 조정해야 한다.

### q3_7. Drain3 miner를 row마다 생성하지 않고 batch 단위로 재사용하는 이유는 무엇인가?

miner 생성과 template state 초기화 비용을 반복하지 않고, 같은 batch 안에서 누적된 template 정보를 활용할 수 있기 때문이다. row별 인스턴스화는 성능을 떨어뜨리고 동일 분석 내 template 일관성도 해친다. 단, 서비스나 로그 포맷이 크게 다른 경우에는 miner state를 분리해야 한다.

### q3_8. cache 사용 시 가장 중요한 무효화 조건은 무엇인가?

입력 로그, 서비스·기간, 분석 옵션뿐 아니라 normalization rule, Known Pattern Registry, Accepted Normal, 모델·embedding 버전이 바뀌면 cache를 무효화해야 한다. 지식 상태가 달라졌는데 이전 결과를 재사용하면 잘못된 판정이 유지될 수 있다. 따라서 cache key에 데이터와 정책 버전을 함께 포함해야 한다.

### q3_9. 증분 처리와 전체 재처리의 trade-off는 무엇인가?

증분 처리는 신규 raw log만 처리해 빠르지만, normalization rule이나 registry가 변경되면 과거 로그의 fingerprint와 판정도 달라질 수 있다. 이런 경우에는 영향 범위를 계산해 선택적 backfill 또는 전체 재처리가 필요하다. 즉 데이터 추가에는 증분이 적합하고, 판정 규칙 변경에는 재계산 전략이 필요하다.

### q3_10. PatternOps Registry를 별도 계층으로 둔 이유는 무엇인가?

코드에 패턴과 대응 규칙을 하드코딩하면 변경마다 배포가 필요하고 승인 이력과 버전 관리가 어렵다. Registry로 분리하면 rule, alias, Known Pattern, 조치 contract를 데이터로 관리하고 Agent가 런타임에 재사용할 수 있다. 대신 schema validation, 버전, 승인자, 적용 범위, rollback 같은 governance가 필요해진다.

### q3_11. MCP-style Tool Registry의 장점은 무엇인가?

Agent가 사용할 수 있는 도구의 이름, 입력 schema, 권한, 실행 방식을 표준화할 수 있다. 도구 호출을 자유 형식 코드 생성과 분리해 안전성과 교체 가능성을 높인다. 향후 자동 조치 기능을 추가할 때도 approval-required, read-only, destructive 같은 정책을 도구 메타데이터에 부여할 수 있다.

### q3_12. LLM을 탐지 단계가 아니라 권고 단계에 집중한 이유는 무엇인가?

탐지는 반복 실행과 재현성이 중요하므로 결정적 정규화, 통계, 군집 알고리즘이 더 적합하다. LLM은 원인 후보와 대응 절차를 구조화하는 데 강하지만 결과 변동성과 비용이 있다. 따라서 핵심 판정은 deterministic pipeline에 두고, 사람이 선택한 사례의 설명과 권고에만 LLM을 사용하는 것이 안전하다.

### q3_13. LLM evaluator를 별도로 사용하는 것의 비용 trade-off는 무엇인가?

생성 모델 외에 평가 호출이 추가되므로 latency와 token 비용이 증가한다. 대신 불완전하거나 위험한 권고가 운영자에게 전달될 가능성을 줄이고, 재생성 feedback을 자동화할 수 있다. 실제 상용화에서는 deterministic 검사로 먼저 탈락시키고, 통과 가능성이 있는 결과에만 evaluator를 호출하는 계층형 평가가 효율적이다.

### q3_14. quality score 90점과 hard-fail을 함께 두면 어떤 장점이 있는가?

점수는 여러 품질 요소의 상대적 수준을 비교하기 좋고, hard-fail은 절대 누락되어서는 안 되는 안전 조건을 보장한다. 두 기준을 결합하면 높은 평균 점수가 필수 항목 누락을 가리는 문제를 방지할 수 있다. 이는 soft evaluation과 policy constraint를 분리한 설계다.

### q3_15. SSE와 WebSocket 중 SSE를 선택한 trade-off는 무엇인가?

분석 진행 상태처럼 서버에서 클라이언트로 단방향 이벤트를 보내는 용도에는 SSE가 구현과 재연결 처리가 단순하다. 양방향 실시간 제어가 필요하다면 WebSocket이 더 적합하지만 운영 복잡성이 증가한다. 현재 흐름에서는 분석 요청은 HTTP, 진행 통지는 SSE로 분리하는 것이 충분하다.

### q3_16. time-window와 similar cluster 분석을 옵션으로 생략할 수 있게 한 이유는 무엇인가?

두 분석은 유용하지만 계산 비용이 크고 모든 요청에서 반드시 필요하지 않다. 빠른 배포 후 점검에서는 기본 fingerprint와 anomaly만 보고, 심층 조사 시 고비용 분석을 켤 수 있다. 이는 정확도·설명력과 응답시간·비용 사이의 서비스 수준을 사용자 목적에 따라 선택하게 하는 설계다.

### q3_17. Accepted Normal을 목록에 유지하는 것이 UI 복잡성을 높이는데도 필요한 이유는 무엇인가?

숨기면 화면은 단순해지지만 해당 패턴의 발생량 변화와 breach를 관측할 수 없다. 목록에 유지하고 상태 badge와 억제 이유를 표시하면 운영자는 정상 승인된 패턴도 지속적으로 추적할 수 있다. 관측성을 보존하는 대신 필터와 정렬을 통해 UI 복잡성을 관리해야 한다.

### q3_18. state vector를 별도 산출물로 두는 장점은 무엇인가?

로그 원문과 단일 anomaly score만으로는 시간 구간의 운영 상태를 비교하기 어렵다. 발생량, severity, 패턴 구성, silence, cluster 변화 등을 벡터로 표현하면 구간 간 유사도, trajectory clustering, transition modeling에 재사용할 수 있다. 다만 feature 정의와 scaling이 바뀌면 버전 관리가 필요하다.

### q3_19. 현재 아키텍처의 단일 장애점은 어디에 있을 가능성이 큰가?

단일 FastAPI 프로세스, 로컬 SQLite, 로컬 ChromaDB, 메모리 cache는 PoC에서는 간단하지만 프로세스 장애와 동시성에 취약하다. 장기 실행 job의 durable state도 별도 저장이 필요하다. 상용화 시 API, worker, queue, transactional DB, vector service, object storage를 분리하고 health check와 retry policy를 추가해야 한다.

### q3_20. 이 시스템에서 가장 중요한 시스템 설계 원칙은 무엇인가?

탐지와 지식 승격은 재현 가능하고 감사 가능해야 하며, 비결정적 생성은 선택적·제한적으로 사용하고, 실제 운영 상태를 바꾸는 행위는 명시적 승인 뒤에만 실행되어야 한다는 원칙이다.

## Meta-Level (핵심 통찰을 검증하는 질문)

### q4_1. 이 프로젝트는 정말 ‘지속 학습’ 시스템인가, 아니면 단순 규칙 저장 시스템인가?

모델 파라미터를 온라인으로 재학습하는 의미의 지속 학습은 아니다. 운영자가 승인한 normalization rule, alias, Known Pattern, Knowledge Card를 다음 분석에 재적용한다는 점에서 외부 메모리와 정책이 지속적으로 갱신되는 운영 학습 시스템이다. 따라서 정확한 표현은 ‘Human-in-the-loop 기반 비파라메트릭 지속 학습’에 가깝다.

### q4_2. 지식 축적이 단순 로그 저장과 다른 점은 무엇인가?

원문 로그를 쌓는 것만으로는 다음 장애에서 바로 재사용할 수 없다. 지식 축적은 로그를 canonical fingerprint로 정규화하고, 원인·조치·검증·적용 범위·승인 이력을 구조화해 검색과 판정에 사용할 수 있게 만드는 과정이다. 즉 저장량이 아니라 재사용 가능한 형태와 governance가 핵심이다.

### q4_3. 이 시스템의 핵심 가치는 이상 탐지 정확도인가, 운영 지식화인가?

둘 다 필요하지만 장기적 차별점은 운영 지식화에 있다. 이상 탐지는 기존 도구로도 가능하지만, 운영자의 판정과 조치를 rule, alias, Knowledge Card, PatternOps contract로 환류하면 시간이 지날수록 반복 검토가 줄어든다. 다만 지식 품질이 낮으면 오히려 오류가 누적되므로 승인과 revoke가 필수다.

### q4_4. ‘Agentic’이라는 표현이 정당화되는 지점은 어디인가?

여러 이름의 모듈이 있다는 것만으로 Agentic하다고 볼 수는 없다. 이 프로젝트에서는 Orchestrator가 상태를 기반으로 도구와 Agent 실행을 조율하고, 조건부 분기, 재시도, evaluator feedback, fallback, 사용자 승인에 따라 workflow를 변경한다. 이러한 stateful control loop가 Agentic workflow를 정당화하는 핵심이다.

### q4_5. 이 시스템은 운영자를 대체하는가?

현재 설계는 운영자를 대체하기보다 전수 확인을 후보 중심 검토로 전환한다. 시스템은 반복 정규화, 패턴 비교, anomaly 계산, 근거 조합을 자동화하고, 사람은 신규 규칙 승인, 정상성 판단, 권고 승인, 실제 조치를 담당한다. 책임과 환경 맥락이 필요한 판단은 여전히 운영자에게 남는다.

### q4_6. 탐지율 100%라는 수치는 어떻게 해석해야 하는가?

문서에 제시된 fixture 또는 검증 시나리오 범위에서 Known Pattern과 신규 이상 후보를 모두 탐지했다는 의미로 봐야 한다. 실제 운영 전체 분포에서 일반적인 100% 성능을 보장한다는 뜻은 아니다. 데이터셋 규모, 클래스 구성, false positive, 기간 분할을 함께 제시해야 성능의 외적 타당성을 평가할 수 있다.

### q4_7. fingerprint 분산 98% 축소가 항상 좋은 결과인가?

동일 장애 변형을 정확히 합친 경우에는 매우 유용하다. 그러나 서로 다른 원인의 로그를 과도하게 병합해도 fingerprint 수는 줄어들 수 있으므로 축소율만으로 품질을 판단하면 안 된다. 병합 precision, split error, 운영자 승인율, 잘못된 Knowledge Card 연결 여부를 함께 측정해야 한다.

### q4_8. 권고 품질 점수가 높아졌다는 것이 실제 장애 복구 성과를 의미하는가?

직접적으로는 아니다. 87.1점에서 95.6점으로 향상된 것은 rubric상 구조·구체성·안전성이 개선됐다는 의미다. 실제 MTTR 감소나 조치 성공률을 증명하려면 권고 채택률, 실행 결과, rollback, 해결 시간 같은 운영 지표를 별도로 측정해야 한다.

### q4_9. RAG를 사용하면 환각 문제가 해결되는가?

RAG는 관련 근거를 제공해 환각 가능성을 줄이지만 자동으로 제거하지는 못한다. 검색 결과가 부정확하거나 모델이 근거를 잘못 해석할 수 있다. 그래서 evidence anchor, deterministic hard-fail, evaluator, 운영자 승인까지 결합해야 한다.

### q4_10. Human-in-the-loop가 병목이 될 가능성은 없는가?

모든 후보를 사람이 승인해야 한다면 병목이 될 수 있다. 따라서 risk, novelty, 발생량, similarity confidence를 이용해 검토 우선순위를 정하고, 반복적으로 승인된 저위험 패턴은 정책 범위 안에서 자동 적용하는 단계적 자동화가 필요하다. 핵심은 사람을 제거하는 것이 아니라 희소한 판단 자원을 중요한 사례에 집중시키는 것이다.

### q4_11. 운영자의 승인 자체가 잘못되면 어떻게 되는가?

잘못된 rule이나 Known Pattern이 다음 분석에 재사용되어 오판이 확산될 수 있다. 이를 막기 위해 승인자, 근거, 적용 범위, 버전, 유효기간, 영향 분석, revoke와 rollback을 기록해야 한다. 고위험 규칙에는 2인 승인이나 shadow 적용 기간을 둘 수도 있다.

### q4_12. Accepted Normal은 anomaly detection의 학습 결과인가, 운영 정책인가?

주로 운영 정책이다. 모델이 정상으로 판단했다는 의미가 아니라, 운영자가 특정 범위에서 허용하기로 승인한 상태다. 따라서 threshold와 기간을 벗어나면 breach로 재탐지되어야 하며, 모델 score와 별도로 관리해야 한다.

### q4_13. 이 프로젝트의 가장 중요한 실패 방지 장치는 무엇인가?

LLM을 핵심 탐지 기준으로 두지 않고, 생성 결과가 자동으로 운영 지식이나 조치로 승격되지 않게 한 것이다. 결정적 분석, quality gate, explicit approval, fallback, revoke가 연속적인 방어 계층을 형성한다. 어느 한 평가 모델의 판단에 시스템 전체를 맡기지 않는다는 점이 중요하다.

### q4_14. 왜 ‘모델 재학습 없이’라는 점이 중요한가?

운영 장애 지식은 자주 추가되지만 매번 모델을 재학습하는 것은 비용, 검증, 배포 위험이 크다. Knowledge Card와 PatternOps Registry를 갱신하면 즉시 검색과 판정에 반영할 수 있다. 다만 장기적으로 데이터가 충분히 쌓이면 retrieval, ranking, planner를 오프라인 학습으로 개선할 수 있다.

### q4_15. 이 시스템이 진짜로 설명 가능한가?

fingerprint를 만든 정규화 규칙, Known Pattern 일치 근거, anomaly feature, cluster, trajectory, Knowledge Card anchor를 제공한다면 상당 부분 설명 가능하다. 하지만 embedding similarity와 HDBSCAN 군집 자체는 직관적으로 설명하기 어려울 수 있다. 따라서 대표 로그, 차이 token, 근접 카드, threshold를 함께 표시해야 설명 가능성이 실제 UI에서 성립한다.

### q4_16. 운영 지식이 시간이 지나며 낡는 문제는 어떻게 다뤄야 하는가?

Knowledge Card와 PatternOps rule에 생성일, 마지막 검증일, 서비스 버전, 적용 환경, 유효기간을 기록해야 한다. 오래 사용되지 않거나 최근 사례와 충돌하는 지식은 review queue로 보내고, 폐기·수정·재승인을 지원해야 한다. 지속 학습에는 추가뿐 아니라 망각과 갱신도 포함된다.

### q4_17. 이 프로젝트의 KPI에서 가장 부족한 부분은 무엇인가?

기술 fixture에서의 탐지율과 권고 점수는 제시됐지만 실제 운영 생산성 KPI가 부족하다. 배포 후 점검 시간, 월간 점검 시간, false positive burden, 권고 채택률, MTTR 변화가 실측되지 않았다. 상용 가치 검증을 위해서는 사용자 행동과 운영 결과 기반 KPI가 우선 보강되어야 한다.

### q4_18. 이 시스템이 실패해도 안전한가?

분석과 권고 생성이 실패해도 원본 로그를 훼손하지 않고, 자동 조치를 수행하지 않으며, fallback과 실패 이력을 제공한다면 fail-safe에 가깝다. 그러나 향후 자동 조치가 추가되면 권한 분리, dry-run, approval gate, timeout, rollback, blast radius 제한이 반드시 필요하다.

### q4_19. Mini AI-Ops의 핵심 통찰을 검증하려면 어떤 실험이 가장 중요한가?

동일 팀이 기존 방식과 시스템 사용 방식으로 같은 배포 후 점검을 수행하는 교차 실험이 중요하다. 점검 시간, 놓친 장애, false positive 검토 수, 원인 파악 시간, 권고 채택률을 비교해야 한다. 이 실험이 반복 업무 절감과 판단 품질 개선이라는 핵심 가설을 직접 검증한다.

### q4_20. 프로젝트의 핵심 메시지를 과장 없이 표현하면 무엇인가?

Mini AI-Ops는 로그 전수 확인을 자동으로 완전히 대체한 시스템이라기보다, 결정적 분석과 운영 지식 재사용을 통해 운영자가 검토해야 할 이상 후보와 대응 근거를 압축하는 Human-in-the-loop AIOps 시스템이다.

## 향후 확장 및 상용화 관점의 질문

### q5_1. 상용화 전에 가장 먼저 검증해야 할 KPI는 무엇인가?

실제 배포 후 점검 시간과 월간 상세 점검 시간의 전후 비교가 우선이다. 여기에 false positive 검토 건수, 놓친 장애, 권고 채택률, MTTR를 함께 측정해야 한다. 기술 점수보다 운영자가 실제로 절약한 시간과 개선된 결과가 구매 가치를 결정한다.

### q5_2. Playwright 기반 E2E 테스트는 어떤 시나리오부터 자동화해야 하는가?

서비스·날짜 선택 후 분석 실행, SSE 진행 표시, 결과 테이블 로딩, fingerprint 선택, 상세 권고 생성, 저장·승인·반려, Accepted Normal breach와 revoke까지 대표 사용자 흐름을 우선 자동화해야 한다. 실패·fallback·재연결 시나리오도 포함해야 한다. 이는 데모 성공이 아니라 실제 배포 안정성을 검증하는 최소 회귀 집합이다.

### q5_3. RAG 평가 체계는 어떻게 구축해야 하는가?

실제 장애 질문과 정답 Knowledge Card를 묶은 Ground Truth fixture를 만들고 Recall@k, MRR, nDCG, 근거 coverage를 측정한다. exact fingerprint 검색과 semantic 검색을 분리 평가하고, 서비스·버전·환경 metadata filter의 효과도 검증해야 한다. 권고 품질 평가는 retrieval 품질과 generation 품질을 따로 측정하는 것이 중요하다.

### q5_4. service_logs_v2 event ontology를 연결하면 무엇이 개선되는가?

서로 다른 서비스 로그를 공통 event type, actor, resource, action, outcome, severity로 정규화할 수 있다. 그러면 문자열 fingerprint를 넘어 서비스 간 비교, 공통 anomaly rule, trajectory 분석이 가능해진다. 장기적으로 incident pattern catalog와 transition model의 입력 schema가 된다.

### q5_5. trajectory clustering을 상용 기능으로 확장하려면 무엇이 필요한가?

시간 window별 state vector 정의, 사건 경계, sequence distance, cluster 안정성 평가가 필요하다. 군집 결과를 실제 incident ticket과 연결해 동일 진행 경로가 같은 원인·조치로 이어지는지 검증해야 한다. 운영 UI에서는 단순 군집 번호보다 대표 경로와 전이 차이를 설명해야 한다.

### q5_6. forecast 또는 transition model은 어떤 데이터를 학습해야 하는가?

시간순 로그 state, 배포 이벤트, 자원 지표, alert, incident 시작·종료, 조치 시점과 결과가 필요하다. 단순 로그 텍스트보다 상태 전이와 실제 장애 outcome이 중요하다. 예측 모델은 ‘다음 로그’를 맞히는 것보다 특정 시간 내 장애 위험이나 전이 확률을 산출하는 방향이 실용적이다.

### q5_7. SkillOps 실행 로그는 planner 개선에 어떻게 활용할 수 있는가?

어떤 상황에서 어떤 도구와 조치 순서를 선택했고, 성공·실패·rollback 결과가 어땠는지를 trajectory로 저장한다. 이를 기반으로 성공한 계획을 검색하거나, 도구 선택 policy를 평가·학습할 수 있다. 단, 실패 실행과 운영 환경 차이를 포함해 데이터 provenance와 안전 필터를 유지해야 한다.

### q5_8. 자동 조치 기능을 도입할 때 필요한 최소 안전장치는 무엇인가?

read-only 진단과 state-changing action을 분리하고, 모든 변경 작업에 dry-run, 명시적 approval, 권한 검증, timeout, idempotency key, rollback, blast radius 제한을 적용해야 한다. 고위험 조치는 2인 승인이나 change window 제약을 둘 수 있다. 조치 전후 evidence와 결과를 audit log로 남겨야 한다.

### q5_9. 멀티테넌트 SaaS로 전환하려면 어떤 아키텍처 변경이 필요한가?

tenant별 데이터 격리, encryption key, vector collection, registry, 권한, 감사 로그를 분리해야 한다. SQLite와 로컬 ChromaDB 대신 다중 사용자 DB와 확장 가능한 vector store, background job queue가 필요하다. 모든 cache key와 Knowledge Card 검색에 tenant scope가 강제되어야 한다.

### q5_10. 대규모 로그 환경에서 storage 전략은 어떻게 바뀌어야 하는가?

원본 로그는 object storage나 log platform에 보관하고, 관계형 DB에는 metadata·fingerprint·분석 결과·승인 이력을 저장하는 계층화가 필요하다. hot window는 빠른 검색 인덱스에, 오래된 데이터는 저비용 저장소에 둔다. retention, compression, PII masking, reprocessing 정책을 함께 설계해야 한다.

### q5_11. OpenSearch나 기존 observability platform과는 어떻게 통합할 수 있는가?

원본 로그 검색과 집계는 OpenSearch, Loki, Splunk 같은 플랫폼에 맡기고, Mini AI-Ops는 분석 job, fingerprint registry, Knowledge Card, approval workflow를 제공할 수 있다. query와 evidence link를 저장해 사용자가 원본 로그로 drill-down하게 한다. 기존 모니터링을 대체하기보다 지식화와 의사결정 계층으로 통합하는 전략이 현실적이다.

### q5_12. 상용 환경에서 모델 공급자 종속성을 줄이려면 어떻게 해야 하는가?

LLM과 embedding 호출을 provider abstraction으로 감싸고, 입력·출력 schema와 evaluation fixture를 고정해야 한다. OpenAI, Azure OpenAI, 사내 모델을 동일 contract로 교체 가능하게 하고, 모델별 품질·비용·latency benchmark를 유지한다. Knowledge Card와 PatternOps는 특정 모델 포맷에 종속되지 않아야 한다.

### q5_13. 비용 관리를 위해 어떤 사용량 정책이 필요한가?

전체 로그가 아니라 선택 fingerprint에만 LLM을 사용하고, embedding batch·cache·중복 document 제외를 적용한다. tenant·서비스별 token budget, 최대 재생성 횟수, 고비용 분석 옵션, rate limit을 설정해야 한다. 비용 dashboard에서 분석 건당·권고 건당 비용과 절감 시간을 함께 보여주는 것이 바람직하다.

### q5_14. 권고의 법적·운영 책임을 어떻게 관리해야 하는가?

권고는 근거와 confidence를 포함한 보조 판단으로 제공하고, 실제 변경은 승인된 운영자 계정으로 실행해야 한다. 누가 어떤 근거를 보고 승인했는지, 도구가 어떤 명령을 수행했는지 감사 가능해야 한다. 고위험 산업에서는 정책 버전, 모델 버전, 데이터 위치, 보존 기간도 규제 요구에 맞춰 관리해야 한다.

### q5_15. 상용화를 위한 보안 요구사항은 무엇인가?

로그 내 개인정보·토큰·URL parameter·credential을 수집 단계에서 masking하고, 전송·저장 암호화와 RBAC를 적용해야 한다. tenant 간 검색 격리, secret vault, tool allowlist, prompt injection 방어, audit log가 필요하다. 외부 LLM 전송이 제한된 고객을 위해 사내 모델 또는 private endpoint 옵션도 고려해야 한다.

### q5_16. Knowledge Card의 lifecycle은 어떻게 관리해야 하는가?

draft, approved, deprecated, revoked 상태와 버전을 두고, 서비스·환경·적용 범위·유효기간·승인자를 기록해야 한다. 새 incident 결과가 기존 카드와 충돌하면 자동 병합하지 말고 review queue로 보낸다. 사용 빈도와 해결 성공률을 기준으로 카드 품질을 재평가할 수 있다.

### q5_17. 고객별 커스터마이징은 어디까지 허용해야 하는가?

로그 parser, normalization rule, severity mapping, Known Pattern, 승인 threshold는 tenant별로 설정할 수 있어야 한다. 반면 core schema, audit 규칙, safety gate는 제품 차원에서 일관되게 유지하는 편이 좋다. 지나친 코드 커스터마이징보다 registry와 policy configuration으로 차이를 흡수해야 유지보수가 가능하다.

### q5_18. 상용 제품의 차별화 포인트는 무엇이 될 수 있는가?

일반적인 로그 anomaly score보다 운영자의 승인 결과를 rule, alias, Knowledge Card, action skill로 재사용하는 폐쇄형 학습 루프가 차별화 포인트가 될 수 있다. 특히 Accepted Normal breach와 revoke, evidence 기반 권고, approval-gated action을 하나의 workflow로 제공하면 운영 지식의 축적과 통제를 함께 해결할 수 있다.

### q5_19. PoC에서 프로덕션으로 넘어갈 때 우선순위는 어떻게 잡아야 하는가?

첫째 실제 운영 KPI와 false positive를 측정하고, 둘째 E2E 회귀와 durable job execution을 확보하며, 셋째 데이터·권한·감사 체계를 강화해야 한다. 그 다음에 trajectory prediction이나 자동 조치 같은 고급 기능을 추가하는 것이 적절하다. 신뢰성 기반이 없는 상태에서 예측 기능을 먼저 확장하면 운영 위험만 커질 수 있다.

### q5_20. 6개월 이후의 현실적인 제품 로드맵은 무엇인가?

1단계는 측정 가능한 로그 분석·지식화 제품, 2단계는 incident trajectory와 유사 경로 추천, 3단계는 사전 위험 예측, 4단계는 approval-gated 반자동 조치다. 각 단계는 이전 단계의 데이터 품질과 운영 신뢰도를 전제로 해야 한다. 최종 목표는 완전 자율 운영보다 증거·승인·rollback이 내장된 예방 중심 AIOps 플랫폼이다.
