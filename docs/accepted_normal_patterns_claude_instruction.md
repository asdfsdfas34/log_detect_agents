# 작업 요청: Anomaly 항목을 Normal로 편입하는 기능 추가

## 배경

현재 로그 탐지 시스템은 anomaly로 탐지된 fingerprint를 `/exceptions`에 등록하여 anomaly/risk 계산에서 제외할 수 있다.
하지만 이 기능은 "정상 편입"이라기보다 "무시/숨김"에 가깝다.

이번에 필요한 기능은 다음이다.

1. 특정 로그 fingerprint가 anomaly increase 또는 spike로 탐지됨
2. 운영자가 해당 항목을 검토한 뒤 "앞으로는 정상 패턴"이라고 승인
3. 이후 동일 패턴은 anomaly count에 포함되지 않음
4. 다만 화면/분석에서는 숨기지 않고 `Accepted Normal` 상태로 표시
5. 승인 당시 기준을 초과하면 다시 anomaly로 탐지

즉, 단순 ignore가 아니라 **사용자 승인 기반 정상 기준선 편입 feedback loop**를 추가해야 한다.

## 현재 참고 위치

주요 파일:

- `LOG_DETECT_AGENTS_BACK/app/db/scenario_store.py`
- `LOG_DETECT_AGENTS_BACK/app/main.py`
- `LOG_DETECT_AGENTS_BACK/app/agents/anomaly_detection.py`
- 관련 테스트: `LOG_DETECT_AGENTS_BACK/tests/`

현재 exception 처리 흐름:

- `exception_registry` 테이블 존재
- `register_exception()`, `fetch_exception_registry()` 존재
- `POST /exceptions`, `GET /exceptions` 존재
- `run_detection_pipeline()` 내부에서 exception fingerprint를 `IGNORED` 처리
- exception은 visible group에서도 제외됨

이번 기능은 exception을 대체하지 말고 별도 개념으로 추가한다.

## 목표 설계

### 1. 새 테이블 추가

`ensure_schema()`에 `accepted_normal_patterns` 테이블을 추가한다.

권장 필드:

```sql
CREATE TABLE IF NOT EXISTS accepted_normal_patterns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint TEXT NOT NULL,
    service_name TEXT DEFAULT '',
    log_level TEXT DEFAULT '',
    normalized_message TEXT DEFAULT '',
    anomaly_type TEXT DEFAULT '',
    accepted_count INTEGER NOT NULL DEFAULT 0,
    accepted_baseline REAL NOT NULL DEFAULT 0,
    max_allowed_count INTEGER DEFAULT NULL,
    max_allowed_multiplier REAL NOT NULL DEFAULT 1.5,
    scope TEXT NOT NULL DEFAULT 'fingerprint',
    reason TEXT NOT NULL,
    approved_by TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    expires_at TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
```

인덱스도 추가한다.

```sql
CREATE INDEX IF NOT EXISTS idx_accepted_normal_patterns_fp
ON accepted_normal_patterns(fingerprint, status);

CREATE INDEX IF NOT EXISTS idx_accepted_normal_patterns_signature
ON accepted_normal_patterns(service_name, log_level, normalized_message, status);
```

### 2. Registry 함수 추가

`scenario_store.py`에 아래 함수들을 추가한다.

- `register_accepted_normal_pattern(...)`
- `fetch_accepted_normal_patterns(...)`
- `revoke_accepted_normal_pattern(id: int)`
- 내부 매칭 함수 `_accepted_normal_rule_for(...)`
- 내부 판정 함수 `_apply_accepted_normal(...)`

등록 시 fingerprint가 `fingerprints` 테이블에 있으면 다음 값을 snapshot으로 저장한다.

- `service_name`
- `log_level`
- `message`
- `normalized_message`
- `occurrence_count`

`accepted_count`는 승인 당시 현재 count를 기본값으로 둔다.
`max_allowed_count`가 명시되지 않으면 `ceil(accepted_count * max_allowed_multiplier)`로 계산해도 된다.

### 3. Anomaly 판정 흐름 수정

`run_detection_pipeline()` 내부에서 `_anomaly_type_for()` 호출 직후 accepted normal을 적용한다.

현재 흐름은 대략 다음과 같다.

```python
anomaly, anomaly_type, severity = _anomaly_type_for(...)
if is_ignored:
    anomaly = False
    anomaly_type = "IGNORED"
    severity = "NONE"
```

이를 다음 개념으로 확장한다.

```python
anomaly, anomaly_type, severity = _anomaly_type_for(...)

accepted_normal = _accepted_normal_rule_for(...)
if accepted_normal:
    anomaly, anomaly_type, severity = _apply_accepted_normal(
        group=g,
        anomaly=anomaly,
        anomaly_type=anomaly_type,
        severity=severity,
        rule=accepted_normal,
    )

if is_ignored:
    anomaly = False
    anomaly_type = "IGNORED"
    severity = "NONE"
```

판정 규칙:

- active rule이 존재하고 현재 count가 허용 범위 이내면:
  - `anomaly = False`
  - `anomaly_type = "ACCEPTED_NORMAL"`
  - `severity = "NONE"`
- active rule이 존재하지만 현재 count가 `max_allowed_count`를 초과하면:
  - `anomaly = True`
  - `anomaly_type = "ACCEPTED_NORMAL_BREACH"`
  - `severity = "HIGH"` 또는 기존 severity 유지
- log level이 승인 당시보다 악화되면 다시 anomaly 처리한다.
  - 예: 승인 당시 `WARN`, 현재 `ERROR`
- `expires_at`이 지났으면 rule을 적용하지 않는다.
- `status != active`이면 rule을 적용하지 않는다.

중요: accepted normal은 exception과 달리 visible group에서 제거하지 않는다.
즉 dashboard fingerprint 목록에는 계속 보여야 한다.

### 4. Response에 상태 노출

`_attach_detection_features()` 또는 fingerprint row 구성 시 다음 필드를 포함하도록 한다.

- `accepted_normal`: boolean
- `accepted_normal_id`: number or empty
- `accepted_normal_reason`: string
- `accepted_normal_status`: string
- `anomaly_type`: `ACCEPTED_NORMAL` 가능

accepted normal 상태인 row는 anomaly count에는 포함하지 않되, fingerprint 목록에는 남아야 한다.

summary에도 다음 값을 추가한다.

- `accepted_normal_count`
- `accepted_normal_breach_count`

### 5. API 추가

`main.py`에 request/response 모델과 endpoint를 추가한다.

권장 API:

```text
GET    /normal-patterns
POST   /normal-patterns
POST   /normal-patterns/{id}/revoke
DELETE /normal-patterns/{id}
```

요청 모델 예시:

```python
class AcceptedNormalPatternRequest(BaseModel):
    fingerprint: str
    service_name: str = ""
    anomaly_type: str = ""
    reason: str
    approved_by: str = ""
    scope: str = "fingerprint"
    max_allowed_multiplier: float = 1.5
    max_allowed_count: int | None = None
    expires_at: str = ""
```

`POST /normal-patterns`는 fingerprint를 정상 편입으로 등록한다.

응답 예시:

```json
{
  "status": "registered",
  "id": 1,
  "fingerprint": "abc123"
}
```

### 6. 기존 `/exceptions`와 역할 구분

아래 의미를 유지한다.

- `/exceptions`: 분석/위험도/화면에서 제외하는 ignore
- `/known-patterns`: 지식화, 추천 재사용
- `/normal-patterns`: 정상 기준선으로 승인하되 계속 관측

exception 로직은 깨지지 않아야 한다.

### 7. 테스트 추가

테스트를 추가한다.

권장 테스트:

1. anomaly로 탐지되는 fingerprint를 normal-pattern으로 등록하면 다음 pipeline 실행에서 anomaly list에서 빠진다.
2. accepted normal fingerprint는 visible fingerprints에는 남아 있다.
3. accepted normal 상태가 fingerprint row에 표시된다.
4. 허용 count를 초과하면 `ACCEPTED_NORMAL_BREACH`로 다시 anomaly가 된다.
5. revoked rule은 더 이상 적용되지 않는다.
6. existing `/exceptions` 동작은 유지된다.

테스트 파일은 기존 스타일에 맞춰 `tests/test_*`에 추가하거나 기존 anomaly/scenario 테스트에 추가한다.

## 구현 시 주의사항

- DB schema 변경은 `ensure_schema()` 안에서 SQLite compatible하게 처리한다.
- destructive migration은 하지 않는다.
- 기존 exception 기능을 normal 편입으로 재사용하지 않는다.
- accepted normal은 anomaly count에서 제외하지만, fingerprint 목록에서는 숨기지 않는다.
- `_PIPELINE_CACHE`가 있다면 normal-pattern 등록/취소 시 cache를 clear해야 한다.
- 기존 API response schema와 프론트엔드가 깨지지 않도록 필드는 additive하게 추가한다.
- 테스트를 실행하고 결과를 보고한다.

## 완료 기준

- `POST /normal-patterns`로 anomaly fingerprint를 정상 편입 등록 가능
- 이후 `/analyze` 또는 detection pipeline 결과에서 해당 fingerprint는 anomaly count에 포함되지 않음
- fingerprint 목록에는 `accepted_normal` 상태로 계속 노출
- 허용 기준 초과 시 다시 anomaly로 탐지
- `/exceptions` 기존 동작 유지
- 관련 테스트 통과
