PatternOps
 ├─ Registry: 지식 저장
 ├─ Matcher: 적용 Contract 검색
 ├─ Skill Planner/Runner: 작업 선택·실행
 └─ Validator/Audit: 결과 검증·이력 관리

아래처럼 표현할 수 있습니다. 현재 구현된 PatternOps는 지식 저장소, 적용 규칙 검색, Skill 실행, 검증·감사 기능을 하나의 Lifecycle로 묶은 구조입니다.

PatternOps
│
├─ 1. Registry: 운영 지식 저장·버전 관리
│  │
│  ├─ Contract Registry
│  │  ├─ KP Contract: Known Pattern
│  │  │  ├─ 대표 Fingerprint
│  │  │  ├─ 장애 분류
│  │  │  ├─ 원인
│  │  │  └─ 권장 조치
│  │  │
│  │  ├─ NR Contract: Normalization Rule
│  │  │  ├─ Match Regex
│  │  │  ├─ Normalization Template
│  │  │  ├─ 적용 우선순위
│  │  │  └─ 과도한 병합 등 Failure Mode
│  │  │
│  │  └─ KC Contract: Knowledge Card
│  │     ├─ 연결 Fingerprint
│  │     ├─ Root Cause
│  │     ├─ Remediation Steps
│  │     ├─ Verification Steps
│  │     └─ Prevention Steps
│  │
│  ├─ Contract 공통 스키마
│  │  ├─ pattern_id: Contract 식별자
│  │  ├─ category / sub_category: 지식 분류
│  │  ├─ lifecycle: draft / active / monitor
│  │  ├─ confidence: 지식 신뢰 수준
│  │  ├─ precondition: 적용 조건
│  │  ├─ operation: 수행하거나 참고할 작업
│  │  ├─ artifact: 생성·연결되는 결과
│  │  ├─ validators: 결과 검증 규칙
│  │  ├─ failure_modes: 오적용 가능성
│  │  └─ source: Known Pattern, Rule, Card 등 출처
│  │
│  ├─ Contract Relation Registry
│  │  ├─ from_pattern_id
│  │  ├─ to_pattern_id
│  │  ├─ edge_type
│  │  ├─ weight
│  │  └─ reason
│  │
│  ├─ Validator Registry
│  │  ├─ validator_id
│  │  ├─ validator_type
│  │  ├─ 적용 Contract
│  │  ├─ 검증 설정
│  │  └─ 활성화 여부
│  │
│  └─ Lifecycle 상태
│     ├─ draft: 검토 또는 초기 등록 상태
│     ├─ active: 분석에 우선 적용
│     └─ monitor: 적용하면서 결과를 관찰
│
├─ 2. Matcher: 적용 가능한 Contract 검색
│  │
│  ├─ 입력 Evidence
│  │  ├─ 원본 Message
│  │  ├─ Normalized Message
│  │  ├─ Fingerprint
│  │  ├─ Service Name
│  │  └─ Log Level
│  │
│  ├─ 매칭 기준
│  │  ├─ Fingerprint 정확히 일치: +0.95
│  │  ├─ Service Scope 일치: +0.15
│  │  ├─ Service Scope 불일치: -0.25
│  │  ├─ Log Level 일치: +0.10
│  │  ├─ Message Template 포함: +0.45
│  │  ├─ Template 유사도 0.86 이상: +0.25
│  │  ├─ Regex 일치: +0.50
│  │  └─ Keyword 일치: +0.12
│  │
│  ├─ 판정 정책
│  │  ├─ 합산 점수 0.45 이상만 채택
│  │  ├─ Confidence 최대 0.99
│  │  ├─ 점수순 정렬
│  │  └─ 로그당 최대 5개 Contract 반환
│  │
│  └─ 매칭 결과
│     ├─ pattern_id
│     ├─ confidence
│     ├─ matched_by: fingerprint, regex, template 등
│     ├─ operation
│     ├─ artifact
│     ├─ validators
│     └─ failure_modes
│
├─ 3. Skill Planner: 필요한 작업 선택
│  │
│  ├─ 실행 Scope
│  │  ├─ log_collection
│  │  ├─ log_analysis
│  │  ├─ anomaly_detection
│  │  ├─ recommendation
│  │  └─ maintenance
│  │
│  ├─ Skill 선택 기준
│  │  ├─ 현재 SharedState Evidence
│  │  ├─ Skill의 requires 충족 여부
│  │  ├─ Scope와 Category 일치 여부
│  │  ├─ Skill 간 선행 의존성
│  │  ├─ Lifecycle 상태
│  │  └─ Priority
│  │
│  ├─ 분석 Skill
│  │  ├─ Log Collection
│  │  ├─ Log Normalization
│  │  ├─ Pattern Fingerprint
│  │  ├─ Known Pattern Match
│  │  └─ Anomaly Detection
│  │
│  ├─ 지식 검색·권고 Skill
│  │  ├─ Knowledge Card Retrieval
│  │  ├─ Chroma Similar Pattern Retrieval
│  │  ├─ Recommendation Generation
│  │  └─ Recommendation Quality Gate
│  │
│  ├─ 유지보수 Skill
│  │  ├─ Duplicate Pattern Detection
│  │  ├─ Fingerprint Merge
│  │  ├─ Pattern Rule Suggestion
│  │  ├─ Exception Suppression
│  │  └─ Resolution Capture
│  │
│  └─ Skill 관계 유형
│     ├─ dependency: 선행 Skill 완료 필요
│     ├─ downstream: 후속 분석
│     ├─ alternative: 대체 검색 경로
│     ├─ guard: 실행 전 보호 조건
│     ├─ adapter: 규칙을 실행 과정에 연결
│     └─ approval_required: 운영자 승인 필요
│
├─ 4. Skill Runner: 선택된 작업 실행
│  │
│  ├─ Skill 내부 구조
│  │  ├─ Precondition: 입력 조건 확인
│  │  ├─ Operation: 함수·Agent·Planner 실행
│  │  ├─ Artifact: 실행 결과 생성
│  │  └─ Validator: 산출물 검증
│  │
│  ├─ 실행 상태
│  │  ├─ planned
│  │  ├─ selected
│  │  ├─ running
│  │  ├─ success
│  │  └─ failed
│  │
│  ├─ 실행 방식
│  │  ├─ Priority 순으로 Skill 정렬
│  │  ├─ Host Agent의 실제 함수에 연결
│  │  ├─ 실행 결과를 SharedState에 누적
│  │  ├─ 실행 이벤트를 SSE로 전달
│  │  └─ 실행 이력을 SQLite에 기록
│  │
│  └─ 승인 경계
│     ├─ 분석·조회 작업은 자동 실행 가능
│     ├─ FP 병합은 운영자 승인 필요
│     ├─ 정규화 규칙 등록은 운영자 승인 필요
│     └─ 권고 지식화는 운영자 승인 필요
│
└─ 5. Validator / Audit: 검증·추적·피드백
   │
   ├─ 정규화 검증
   │  ├─ Regex 컴파일 가능 여부
   │  ├─ 변환 전후 Sample 확인
   │  └─ Message Template 생성 여부
   │
   ├─ Fingerprint 검증
   │  ├─ Stable Fingerprint 생성 여부
   │  ├─ 발생 건수 보존 여부
   │  └─ Alias 생성 여부
   │
   ├─ 패턴 매칭 검증
   │  ├─ Confidence Threshold
   │  ├─ Match Source 존재 여부
   │  └─ Fingerprint 또는 Similarity 근거
   │
   ├─ 이상 탐지 검증
   │  ├─ Baseline 비교 여부
   │  ├─ Severity 산정 근거
   │  └─ Suppression 적용 사유
   │
   ├─ 권고 검증
   │  ├─ Evidence와 조치 연결
   │  ├─ Action Owner 존재
   │  ├─ 품질 점수 80점 이상
   │  ├─ Hard-fail 사유 검사
   │  └─ 실패 시 재생성 또는 Fallback
   │
   ├─ Evidence 기록
   │  ├─ pattern_ops_matches
   │  ├─ pattern_ops_skill_plan
   │  ├─ pattern_ops_skill_executions
   │  └─ pattern_ops_validator_results
   │
   ├─ 감사 이력
   │  ├─ Known Pattern 등록
   │  ├─ Normalization Adapter 등록
   │  ├─ Fingerprint Merge
   │  ├─ Duplicate Candidate 반려
   │  └─ 승인된 해결 결과 Capture
   │
   └─ 실패 기록
      ├─ 실패 Agent·Skill
      ├─ 오류 원인
      ├─ Validator 실패 내용
      ├─ Retry Count
      └─ Graceful Degradation 결과
```

전체 Lifecycle로 연결하면 다음과 같습니다.

```text
패턴 발견
 → Matcher가 기존 Contract 검색
 → 미등록·중복 패턴 후보 생성
 → Planner가 필요한 Skill 선택
 → Runner가 분석·검색 작업 실행
 → Validator가 결과 검증
 → 운영자가 승인·반려
 → Registry에 Contract와 Action 저장
 → 이후 분석에서 재사용
```

핵심적으로 각 구성요소의 책임은 다음처럼 구분됩니다.

| 구성요소 | 핵심 질문 |
|---|---|
| Registry | 어떤 운영 지식을 보유하고 있는가? |
| Matcher | 현재 로그에 어떤 지식을 적용할 수 있는가? |
| Planner | 현재 Evidence에서 어떤 작업이 필요한가? |
| Runner | 선택된 작업을 어떻게 실행할 것인가? |
| Validator | 실행 결과를 신뢰할 수 있는가? |
| Audit | 누가 무엇을 승인·변경했고 결과가 어땠는가? |

단, 현재 PatternOps가 모든 Skill을 완전히 자율적으로 실행하는 것은 아닙니다. 실제 Operation이 Host Agent 함수에 연결된 Skill만 자동 실행되며, Fingerprint 병합·정규화 규칙 등록·Knowledge Card 생성과 같은 지식 변경 작업은 명시적인 운영자 승인을 요구합니다.

##

 실제 DB에서 서로 연결되는 사례를 기준으로 보면 다음 3개 Contract가 하나의 지식 흐름을 구성합니다.

## 1. 정규화 Contract 예시

**Contract:** `NR-000147`  
**유형:** Pattern Normalization Rule

```text
입력 패턴:
PARAMETER I_SPERNR_TO of FUNCTION TEST_INT_ENTRUST_LIST
(SETTER): cannot convert String into NUM(숫자)

정규화 결과:
PARAMETER I_SPERNR_TO of FUNCTION TEST_INT_ENTRUST_LIST
(SETTER):cannot convert String into NUM(*)
```

이 Contract는 정규식을 이용해 `NUM(10)`, `NUM(20)`처럼 달라지는 숫자를 `NUM(*)`로 치환합니다.

주요 정보는 다음과 같습니다.

- `analysis_type`: `normalize_then_match`
- `normalization_rule_id`: `147`
- `priority`: `120`
- `confidence`: `HIGH`
- `lifecycle`: `active`

즉, 여러 로그 메시지를 동일한 Template으로 통합하는 역할입니다.

## 2. Known Pattern Contract 예시

**Contract:** `KP-000151`  
**대표 Fingerprint:** `FP-8CFC36`  
**유형:** Known Pattern

```text
원인:
Duplicate Pattern 후보 DUP-E92442823CD5의 운영자 승인

권고:
Pattern Normalization Rule #147을 적용해
중복 Fingerprint를 하나로 그룹화
```

정규화 규칙 147을 통해 중복 Fingerprint가 병합됐고, 최종 Canonical Fingerprint인 `FP-8CFC36`이 Known Pattern으로 등록된 사례입니다.

이후 동일 Fingerprint가 발생하면 PatternOps는 다음 정보를 제공합니다.

- 이미 확인된 Known Pattern이라는 사실
- 패턴이 생성된 원인
- 적용된 정규화 규칙
- 기존 권고 조치
- 매칭 신뢰도와 검증 조건

## 3. Knowledge Card Contract 예시

**Contract:** `KC-KC-005815007`  
**연결 Fingerprint:** `FP-8CFC36`  
**유형:** Approved Case

이 Contract에는 동일 장애에 대해 운영자가 승인한 상세 지식이 저장되어 있습니다.

```text
근본 원인:
I_SPERNR_TO 파라미터에 비숫자 문자열이 전달되어
SAP RfcTypeConversionException 발생

권장 조치:
입력값 숫자 형식 검증
예외 처리 및 상세 로그 보강
단위·통합 테스트 추가

검증 방법:
동일 FP 재발 여부 확인
오류율과 로그 발생량 감소 확인
```

Known Pattern Contract가 “이미 알고 있는 패턴”을 나타낸다면, Knowledge Card Contract는 “과거에 어떻게 원인을 확인하고 조치했는가”를 제공합니다.

## Contract 간 관계

세 Contract의 관계는 다음과 같습니다.

```text
NR-000147
정규화 규칙
    ↓
서로 다른 로그를 동일 Template으로 변환
    ↓
FP-8CFC36
Canonical Fingerprint
    ↓
┌──────────────────────┬────────────────────────┐
│ KP-000151            │ KC-KC-005815007        │
│ Known Pattern        │ Approved Case          │
│ 패턴 분류·원인 요약    │ 상세 조치·검증·예방 지식  │
└──────────────────────┴────────────────────────┘
```

| Contract | 역할 | 연결 기준 |
|---|---|---|
| `NR-000147` | 로그 표현 통합 | Regex와 Template |
| `KP-000151` | Known Pattern 판정 | Canonical FP `FP-8CFC36` |
| `KC-KC-005815007` | 승인된 해결 사례 제공 | 동일 FP `FP-8CFC36` |

중요한 점은 세 Contract가 하나로 병합된 것은 아니라는 것입니다. 각각 독립된 Contract로 존재하며, 하나의 로그가 분석될 때 역할별로 함께 연결됩니다.

- 정규화 Contract는 로그를 동일한 형태로 만듭니다.
- Known Pattern Contract는 해당 FP가 기존 장애인지 판정합니다.
- Knowledge Card Contract는 기존 원인과 해결 방법을 제공합니다.

현재 `KP-000151`과 `KC-KC-005815007`은 `FP-8CFC36`을 명시적으로 공유합니다. 반면 `NR-000147`은 Fingerprint를 직접 저장하지 않고 Regex와 Template으로 연결됩니다. 별도의 `pattern_contract_edges` 관계가 저장된 사례는 아니며, 정규화 결과와 공유 Fingerprint를 통해 분석 흐름상 연결되는 구조입니다.