### 핵심 사용자 시나리오

## 시나리오 1 : 로그 수집 및 Fingerprint 생성

* ID : SC-001

* 상황 : 게시판, 로그인, 배치 시스템 등에서 로그가 지속적으로 발생하는 상황

* 목표 : 시스템별 로그를 수집하고, 정규식으로 장애를 Fingerprint 기준으로 그룹화한다.

* 사전 조건

  * 로그 수집 대상 시스템이 등록되어 있다.

  * 로그 수집 API 또는 파일 경로가 설정되어 있다.

## 상세 흐름

| 단계 | 사용자 행동    | 시스템 동작               | 비고                  |
| -- | --------- | -------------------- | ------------------- |
| 1  | 배치 서비스 실행 | 로그 발생                | ERROR, WARN, INFO 등 |
| 2  | -         | Log Collector가 로그 수집 | 배치                  |
| 3  | -         | Fingerprint 생성       | FP-000123           |
| 4  | -         | 동일 Fingerprint 집계    | 발생 건수 계산            |
| 5  | -         | 로그 DB 저장             | service_logs        |

## 입력 예시

```json
[
{
  "service_name":"board-service",
  "log_level":"ERROR",
  "message":"개체 참조가 개체의 인스턴스로 설정되지 않았습니다.",
  "stacktrace":"System.NullReferenceException at BoardService.GetPost(1)",
  "source":"BoardService.cs",
  "created_at":"2026-06-12 10:00:00"
},
{
"service_name":"board-service",
"log_level":"ERROR",
"message":"개체 참조가 개체의 인스턴스로 설정되지 않았습니다.",
"stacktrace":"System.NullReferenceException at BoardService.GetPost(2)",
"source":"BoardService.cs",
"created_at":"2026-06-12 10:00:00"
}
...
]
```

## 기대 출력

```json
{
  "fingerprint":"FP-000123",
  "occurrence_count":10,
  "log_level":"ERROR",
  "message":"개체 참조가 개체의 인스턴스로 설정되지 않았습니다.",
  "stacktrace":"System.NullReferenceException at BoardService.GetPost(*)",
  "service_name":"board-service"
}
```

## 성공 기준

* 기준 1 : 로그가 정규화되어 저장된다.

* 기준 2 : 동일 장애가 하나의 Fingerprint로 그룹화된다.

***

## 시나리오 2 : 로그 분석 및 패턴 분류

* ID : SC-002

* 상황 : 수집된 로그에 대한 유형 분류가 필요한 상황

* 목표 : 로그 유형 분류 및 Known Pattern 여부를 판단한다.

* 사전 조건

  * 로그가 수집 및 저장되어 있다.

  * Known Pattern Registry가 존재한다.

## 상세 흐름

| 단계 | 사용자 행동         | 시스템 동작           | 비고                                     |
| -- | -------------- | ---------------- | -------------------------------------- |
| 1  | 대시보드에서 로그분석 실행 | 수집 로그 조회         | message,service_name, stacktrace 기준    |
| 2  | -              | 로그 유형 분류         | Exception, Timeout 등                   |
| 3  | -              | Known Pattern 조회 | 등록 패턴 검색(rule base + confidence score) |
| 4  | -              | 신규 패턴 여부 판단      | 신규/기존                                  |
| 5  | -              | 분석 결과 저장         | 분석 결과 DB                               |

## 입력 예시

```json
{
  "fingerprint":"FP-000123",
  "occurrence_count":10,
  "log_level":"ERROR",
  "message":"개체 참조가 개체의 인스턴스로 설정되지 않았습니다.",
  "stacktrace":"System.NullReferenceException at BoardService.GetPost(*)",
  "service_name":"board-service"
}
```

## 기대 출력

```json
{
  "fingerprint":"FP-000123",
  "category":"Exception",
  "sub_category":"NullReference",
  "is_known_pattern":false,
  "is_new_pattern":true
}
```

## 성공 기준

* 기준 1 : 로그 유형이 올바르게 분류된다.

* 기준 2 : Known Pattern 여부가 판별된다.

* 기준 3: Known Pattern 인 경우 사용자 대시보드에 노출하지 않는다.

***

## 시나리오 3 : 이상 탐지

* ID : SC-003

* 상황 : 장애 가능성이 있는 로그 패턴이 발생한 상황

* 목표 : 이상 징후를 자동 탐지한다.

* 사전 조건

  * 기존 분석 결과가 생성되어 있다.

  * 과거 로그 통계 데이터가 존재한다.

## 상세 흐름

| 단계 | 사용자 행동 | 시스템 동작      | 비고                |
| -- | ------ | ----------- | ----------------- |
| 1  | -      | 발생 빈도 확인    | 기준선 조회            |
| 2  | -      | 급증 여부 분석    | Spike Detection   |
| 3  | -      | 신규 예외 탐지    | New Error         |
| 4  | -      | 로그 미발생 탐지   | Silence Detection |
| 5  | -      | 이상 탐지 결과 저장 | anomaly_results   |

## 입력 예시

```json
{
  "fingerprint":"FP-000123",
  "daily_count":10,
  "baseline_count":5
}
```

## 기대 출력

```json
{
  "anomaly_detected":true,
  "spike_ratio":200,
  "severity":"HIGH"
}
```

## 성공 기준

* 기준 1 : 급증 로그가 탐지된다.

* 기준 2 : 신규 예외가 탐지된다.

***

## 시나리오 4 : 해결방안 추천

* ID : SC-005

* 상황 : 감지된 장애에 대한 대응 방안이 필요한 상황

* 목표 : 과거 사례 기반 + LLM 답변을 정리하여 해결방안을 제공한다.

* 사전 조건

  * 감지 결과가 존재한다.

  * RAG DB가 구축되어 있다.

## 상세 흐름

| 단계 | 사용자 행동 | 시스템 동작    | 비고       |
| -- | ------ | --------- | -------- |
| 1  | -      | 감지 내역 선택  | 대시보드     |
| 2  | -      | 유사 사례 검색  | RAG 검색   |
| 3  | -      | 관련 사례 추출  | Top-K    |
| 4  | -      | LLM 답변 생성 | 해결방안 생성  |
| 5  | -      | 근거 데이터 첨부 | Evidence |
| 6  | -      | 추천 결과 제공  | 화면 표시    |

## 입력 예시

```json
{
  "fingerprint":"FP-000123"
}
```

## 기대 출력

```json
{
  "cause":"Null 객체 참조",
  "recommendation":"Null Check 추가",
  "confidence":"HIGH"
}
```

## 성공 기준

* 기준 1 : 유사 사례가 검색된다.

* 기준 2 : 해결방안과 근거가 제공된다.

***

## 시나리오 5 : 예외 등록

* ID : SC-006

* 상황 : 실제 장애가 아닌 정상 로그가 반복 발생하는 상황

* 목표 : 오탐을 줄이기 위해 예외 처리한다, 예외 처리된 내용과 유사하다고 판단된 내용은 시나리오 3에서 예외 처리된다.

* 사전 조건

  * 감지 내역이 존재한다.

## 상세 흐름

| 단계 | 사용자 행동   | 시스템 동작      | 비고 |
| -- | -------- | ----------- | -- |
| 1  | 감지 내역 조회 | 상세 정보 표시    |    |
| 2  | 예외 등록 선택 | 입력 화면 표시    |    |
| 3  | 예외 사유 입력 | 검증 수행       |    |
| 4  | 저장 요청    | 예외 DB 저장    |    |
| 5  | -        | 이후 탐지 제외 처리 |    |
| 6  | -        | 감사 이력 저장    |    |

## 입력 예시

```json
{
  "fingerprint":"FP-000456",
  "reason":"배치 작업 중 정상 발생"
}
```

## 기대 출력

```json
{
  "exception_registered":true
}
```

## 성공 기준

* 기준 1 : 예외 대상 DB에 저장된다.

* 기준 2 : 이후 감지 대상에서 제외된다.

***

## 시나리오 6 : AI 결과 승인, 지식축적 및 조회

* ID : SC-007

* 상황 : AI가 제시한 분석 결과를 검증/조회 하는 상황

* 목표 : 화면에서 제시된 추천 결과를 사용자가 채택하여 실제 조치한 결과를 등록하여 케이스 카드를 생성/저장 한다.

* 사전 조건

  * 추천 결과가 생성되어 있다.

## 상세 흐름

| 단계 | 사용자 행동    | 시스템 동작     | 비고 |
| -- | --------- | ---------- | -- |
| 1  | AI 결과 조회  | 결과 표시      |    |
| 2  | 승인 또는 반려  | 선택 입력      |    |
| 3  | 승인 처리     | 답변 DB 저장   |    |
| 4  | 케이스 카드 생성 | 지식 카드 생성   |    |
| 5  | 유사 사례 연결  | RAG 데이터 생성 |    |
|    |           |            |    |

## 입력 예시

```json
{
  "fingerprint":"FP-000123",
  "cause":"Null 객체 참조",
  "recommendation":"Null Check 추가",
  "action":"Null Check 추가 예정",
  "confidence":"HIGH",
  "result":"approved",
}
```

## 기대 출력

```json
{
  "knowledge_registered":true,
  "card_id":"KC-001"
}
```

## 성공 기준

* 기준 1 : 승인된 결과가 지식 DB에 저장된다.

* 기준 2 : 이후 유사 장애 분석에 활용 가능하다.

### 시나리오 우선순위 매트릭스

|        |         |        |        |
| ------ | ------- | ------ | ------ |
| 시나리오   | 비즈니스 가치 | 구현 난이도 | PoC 포함 |
| SC-001 | 중간      | 낮음     | 네      |
| SC-002 | 높음      | 높음     | 네      |
| SC-003 | 중간      | 중간     | 네      |
| SC-004 | 높음      | 높음     | 네      |
| SC-005 | 중간      | 중간     | 네      |
| SC-006 | 높음      | 중간     | 네      |
|        |         |        |        |
|        |         |        |        |
