# 로그 오류 패턴 유형화 설계 가이드

가능한 설계 흐름은 이렇게 잡는 게 가장 좋습니다.

```text
raw log
→ template / entity-type normalization
→ event embedding
→ time-window state vector
→ trajectory construction
→ trajectory clustering
→ incident pattern catalog
→ 선택적으로 flow matching / transition model
```

핵심은 **template extraction은 "로그 문장 정규화"**, **embedding은 "정규화된 event를 벡터 공간에 놓는 것"**, **trajectory clustering은 "시간에 따른 event/state sequence를 묶는 것"**, **flow matching은 "그 상태가 앞으로 어떻게 흘러갈지 생성/예측하는 동역학 모델"**이라는 점입니다.

---

# 1. 먼저 템플릿 추출이란 무엇인가?

로그는 대개 반정형 텍스트입니다.

예를 들어:

```text
2026-06-26 10:01:12 ERROR user 12345 failed login from 10.1.2.3
2026-06-26 10:01:15 ERROR user 87321 failed login from 10.1.2.9
2026-06-26 10:02:01 ERROR user 99512 failed login from 10.1.2.7
```

사람이 보면 같은 유형의 로그입니다. 하지만 문자열은 다릅니다. 그대로 임베딩하거나 클러스터링하면 user id, IP, timestamp 같은 variable 때문에 같은 유형이 흩어질 수 있습니다.

그래서 이를 다음처럼 정규화합니다.

```text
ERROR user <*> failed login from <IP>
```

이게 **log template**입니다.

즉 템플릿 추출은:

> **raw log line에서 변하는 값은 parameter로 치환하고, 변하지 않는 구조는 event type으로 남기는 작업**입니다.

대표적인 온라인 로그 파서인 **Drain**은 고정 깊이 parse tree를 사용해 raw log message를 streaming 방식으로 빠르게 template으로 파싱하는 접근이고, **Spell**은 longest common subsequence 기반으로 streaming log parsing을 수행합니다. ([IEEE Xplore][1])

---

# 2. 템플릿 추출은 "엔티티 타입 정규화"에 가깝다

여기서 중요한 건 template extraction을 단순 문자열 처리로 보지 말고, **로그 세계의 event ontology를 만드는 작업**으로 보는 것입니다.

예를 들어 raw log에서 이런 값들을 뽑습니다.

```json
{
  "timestamp": "2026-06-26T10:01:12",
  "severity": "ERROR",
  "service": "auth-api",
  "template": "user <*> failed login from <IP>",
  "template_id": "auth_failed_login_ip",
  "entities": {
    "user_id": "12345",
    "ip": "10.1.2.3"
  }
}
```

여기서 분리해야 하는 축은 대략 다음입니다.

| 축                  | 예시                                   | 역할              |
| ------------------ | ------------------------------------ | --------------- |
| `template_id`      | `redis_timeout`, `db_pool_exhausted` | event type      |
| `severity`         | INFO, WARN, ERROR, FATAL             | 강도              |
| `service`          | api-gateway, auth-api, payment       | 발생 주체           |
| `dependency`       | redis, postgres, kafka               | 의존 시스템          |
| `entity_type`      | user, order, pod, node, shard        | 영향을 받은 대상 타입    |
| `entity_id`        | user_123, pod_abc                    | 개별 대상           |
| `error_code`       | HTTP_500, ECONNRESET                 | 표준 오류 코드        |
| `parameter_values` | timeout=3000ms, retry=5              | 수치/상태 parameter |

이 작업이 중요한 이유는, 이후 clustering의 단위가 raw 문장이 아니라 다음처럼 바뀌기 때문입니다.

```text
"redis timeout on cache service"
```

가 아니라:

```json
{
  "event_type": "dependency_timeout",
  "dependency": "redis",
  "service": "cache-api",
  "severity": "ERROR"
}
```

가 됩니다.

이렇게 해야 "Redis timeout", "Redis connection timeout", "cache backend timeout" 같은 표현 차이를 하나의 유형으로 묶을 수 있습니다.

---

# 3. 템플릿 추출의 실무 방식

실무적으로는 4단계로 나눕니다.

## 3.1 Pre-normalization

먼저 노이즈가 큰 token을 치환합니다.

```text
timestamp → <TIME>
uuid → <UUID>
ip → <IP>
hex → <HEX>
number → <NUM>
url → <URL>
path → <PATH>
pod name → <POD>
trace id → <TRACE_ID>
```

예:

```text
GET /api/v1/orders/92831 failed with status 500 in 391ms
```

정규화:

```text
GET <PATH> failed with status <STATUS_CODE> in <DURATION>
```

이 단계는 rule-based가 강합니다. IP, UUID, timestamp, 숫자, path, email 같은 건 정규식으로 충분히 잘 잡힙니다.

---

## 3.2 Template discovery

비슷한 구조의 로그들을 모아 template을 만듭니다.

예:

```text
connection to redis-01 timed out after 3000ms
connection to redis-02 timed out after 5000ms
connection to redis-03 timed out after 3000ms
```

템플릿:

```text
connection to <*> timed out after <DURATION>
```

Drain 같은 방식은 token 길이, 앞쪽 token, similarity 등을 활용해 fixed-depth tree에서 후보 template을 찾습니다. 이 방식은 streaming 로그에 적합하고, 대규모 로그에서 빠르게 동작하도록 설계되었습니다. ([IEEE Xplore][1])

Spell류는 로그 간 공통 subsequence를 찾아서 변하는 부분을 parameter로 치환합니다. Spell은 streaming parser로 제안되었고 LCS 기반 접근을 사용합니다. ([Users at Utah][2])

---

## 3.3 Template canonicalization

template이 너무 잘게 쪼개지면 안 됩니다.

예:

```text
Redis connection timed out
Redis command timed out
Redis request timed out
```

이 셋을 각각 다른 template으로 두면 clustering이 파편화됩니다.

그래서 더 상위 canonical event type을 둡니다.

```text
redis_timeout
```

또는 더 일반화하면:

```text
dependency_timeout
```

이때 계층을 만들 수 있습니다.

```text
L1: dependency_error
L2: dependency_timeout
L3: redis_timeout
L4: redis_command_timeout
```

당신이 XBRL에서 L1~L4 line hierarchy를 다뤘던 것처럼, 로그도 event taxonomy를 계층화하는 게 좋습니다.

---

## 3.4 Entity binding

로그 템플릿만 있으면 "무슨 일이 일어났는지"는 알 수 있지만, "어디서 일어났는지"가 약합니다.

그래서 service, host, pod, endpoint, dependency, customer, tenant, region 등을 붙입니다.

예:

```json
{
  "template_id": "dependency_timeout",
  "canonical_event_id": "redis_timeout",
  "service": "checkout-api",
  "dependency": "redis",
  "region": "ap-northeast-2",
  "severity": "ERROR"
}
```

이게 나중에 root cause propagation을 보려면 매우 중요합니다.

---

# 4. 그럼 템플릿을 어떻게 임베딩하나?

로그 임베딩은 크게 세 수준이 있습니다.

```text
event embedding
window embedding
trajectory embedding
```

각각 목적이 다릅니다.

---

## 4.1 Event embedding

event embedding은 한 로그 event 또는 template을 벡터화하는 것입니다.

입력은 raw log가 아니라 정규화된 구조가 좋습니다.

예:

```json
{
  "template_id": "redis_timeout",
  "severity": "ERROR",
  "service": "checkout-api",
  "dependency": "redis",
  "error_code": "ETIMEDOUT"
}
```

이를 문자열로 만들 수도 있습니다.

```text
service=checkout-api dependency=redis severity=ERROR event=redis_timeout code=ETIMEDOUT
```

또는 field별 embedding을 합칠 수 있습니다.

```text
event_embedding =
  template_embedding
  + service_embedding
  + dependency_embedding
  + severity_embedding
  + error_code_embedding
```

일반적인 방법은 세 가지입니다.

| 방식                    | 설명                                      | 장점       | 단점                |
| --------------------- | --------------------------------------- | -------- | ----------------- |
| Text embedding        | template text를 임베딩                      | 구현 쉬움    | 구조 정보 약함          |
| Categorical embedding | template_id, service_id 등을 각각 embedding | 구조적이고 빠름 | 신규 template 대응 필요 |
| Hybrid embedding      | text + categorical + numeric feature 결합 | 가장 실무적   | feature 설계 필요     |

추천은 **hybrid**입니다.

예:

```text
event_vector =
concat(
  text_embedding(template_text),
  embedding(template_id),
  embedding(service),
  embedding(dependency),
  onehot/severity_score,
  numeric_features
)
```

---

## 4.2 Window embedding

trajectory clustering을 하려면 개별 로그 하나가 아니라 시간 window가 필요합니다.

예를 들어 1분 또는 5분 단위로 묶습니다.

```text
window_t = 2026-06-26 10:00~10:05
```

이 window 안에 이런 event가 있다고 해보겠습니다.

```text
redis_timeout: 42
retry_exceeded: 18
db_pool_wait: 9
api_5xx: 31
```

그러면 window vector는 다음처럼 만들 수 있습니다.

```json
{
  "redis_timeout_count": 42,
  "retry_exceeded_count": 18,
  "db_pool_wait_count": 9,
  "api_5xx_count": 31,
  "latency_p95": 1850,
  "error_rate": 0.07
}
```

즉 window embedding은 로그 event의 bag-of-events + metric summary입니다.

더 세련되게는:

```text
window_embedding =
weighted_mean(event_embeddings)
+ count_vector(template_id)
+ metric_features
+ topology_features
```

여기서 topology_features는 service dependency graph에서 나온 정보입니다.

예:

```text
checkout-api → redis
checkout-api → payment-api
payment-api → postgres
```

장애 분석에서는 이 graph 정보가 매우 중요합니다.

---

## 4.3 Trajectory embedding

trajectory는 window들의 sequence입니다.

```text
T = [x_1, x_2, x_3, ..., x_n]
```

예:

```text
x1: normal
x2: cache miss 증가
x3: redis timeout 증가
x4: retry 증가
x5: db pool saturation
x6: api 5xx 증가
```

trajectory embedding은 이 전체 sequence를 하나의 벡터로 요약합니다.

방법은 여러 가지입니다.

| 방법                   | 설명                                | 적합 상황                    |
| -------------------- | --------------------------------- | ------------------------ |
| 통계 요약                | 평균, max, slope, spike count       | 간단한 baseline             |
| sequence model       | GRU/LSTM/Transformer encoder      | 로그 순서가 중요할 때             |
| shapelet             | 특정 짧은 패턴 존재 여부                    | 해석 가능성 필요할 때             |
| DTW distance 기반      | 시간축이 늘어나거나 줄어드는 패턴 비교             | 장애 속도가 케이스마다 다를 때        |
| contrastive learning | 같은 incident는 가깝게, 다른 incident는 멀게 | 라벨/incident ticket이 있을 때 |

---

# 5. Trajectory clustering이란?

Trajectory clustering은 단일 event를 묶는 게 아니라, **시간에 따른 변화 경로를 묶는 것**입니다.

단일 로그 clustering은:

```text
redis timeout 로그끼리 묶기
```

trajectory clustering은:

```text
redis timeout → retry storm → db pool exhaustion → api 5xx
```

라는 **진행 패턴 전체를 묶는 것**입니다.

즉 관심 단위가 다릅니다.

```text
event clustering: "무슨 로그인가?"
trajectory clustering: "어떤 장애 진행 경로인가?"
```

---

# 6. Trajectory clustering 방법론

## 방법 A: Fixed-window feature clustering

가장 단순한 방법입니다.

장애 전후 일정 시간 구간을 자릅니다.

```text
incident_start - 30min ~ incident_start + 30min
```

각 trajectory를 같은 길이의 벡터로 만듭니다.

```text
[redis_timeout_count_t1, ..., redis_timeout_count_t12,
 retry_count_t1, ..., retry_count_t12,
 db_pool_count_t1, ..., db_pool_count_t12]
```

그리고 k-means, GMM, HDBSCAN 같은 클러스터링을 적용합니다.

장점은 간단합니다. 단점은 장애 속도가 다르면 약합니다.

예를 들어 어떤 장애는 5분 만에 터지고, 어떤 장애는 40분에 걸쳐 천천히 커집니다. fixed-window 방식은 이런 시간 왜곡에 약합니다.

---

## 방법 B: DTW 기반 trajectory clustering

DTW, Dynamic Time Warping은 두 시계열이 시간축에서 조금 늘어나거나 줄어들어도 유사성을 계산하는 방법입니다. DTW는 일반적으로 길이가 다르거나 진행 속도가 다른 sequence 간 유사도 측정에 사용됩니다. ([arXiv][3])

예를 들어 두 장애가 있습니다.

```text
A: redis timeout → retry → db pool → 5xx   10분
B: redis timeout → retry → db pool → 5xx   40분
```

fixed distance로 보면 다르게 보일 수 있습니다. 하지만 DTW는 "패턴 순서가 비슷하다"고 봅니다.

로그 trajectory에서는 매우 유용합니다. 왜냐하면 장애 진행 속도는 시스템 부하, retry 설정, autoscaling 정책에 따라 달라질 수 있기 때문입니다.

구조는 다음과 같습니다.

```text
1. 각 incident를 sequence로 표현
2. sequence 간 DTW distance 계산
3. distance matrix 생성
4. hierarchical clustering / DBSCAN / HDBSCAN 적용
```

예:

```text
Trajectory A = [normal, redis_timeout, retry, db_pool, 5xx]
Trajectory B = [normal, redis_timeout, redis_timeout, retry, db_pool, 5xx]
```

DTW는 중간 반복이 있어도 두 sequence를 유사하게 볼 수 있습니다.

---

## 방법 C: Edit distance / sequence alignment 기반 clustering

event sequence를 문자열처럼 봅니다.

```text
A = [CACHE_MISS, REDIS_TIMEOUT, RETRY, DB_POOL, API_5XX]
B = [REDIS_TIMEOUT, RETRY, DB_POOL, API_5XX]
C = [KAFKA_LAG, CONSUMER_REBALANCE, TIMEOUT]
```

이때 Levenshtein distance, LCS distance, weighted edit distance를 쓸 수 있습니다.

Spell이 로그 template 추출에서 LCS를 쓰는 것처럼, sequence alignment는 로그 진행 패턴 비교에도 자연스럽습니다. ([Users at Utah][2])

장점은 해석 가능성이 좋다는 점입니다.

```text
A와 B는 CACHE_MISS 하나만 다르고 나머지 progression이 같다
```

라고 설명할 수 있습니다.

단점은 수치 metric이나 강도 정보를 반영하기 어렵습니다.

---

## 방법 D: Sequence encoder + clustering

Transformer, GRU, TCN 같은 sequence encoder로 trajectory를 하나의 embedding으로 바꿉니다.

```text
[x1, x2, x3, ..., xn] → z_trajectory
```

그 다음 `z_trajectory`를 HDBSCAN, k-means, hierarchical clustering으로 묶습니다.

좋은 입력은 다음처럼 구성합니다.

```text
x_t = [
  event_count_vector,
  service_error_vector,
  dependency_error_vector,
  latency_features,
  saturation_features,
  topology_features
]
```

장점은 복잡한 패턴을 잘 잡을 수 있다는 점입니다. 단점은 해석이 어렵고, 학습 데이터가 필요합니다.

incident ticket, alert label, postmortem RCA가 있으면 contrastive learning을 쓸 수 있습니다.

```text
same incident type → 가까이
different incident type → 멀리
false alarm → incident와 멀리
```

---

## 방법 E: Shapelet / motif mining

장애 trajectory 안에서 반복적으로 등장하는 짧은 subsequence를 찾습니다.

예:

```text
redis_timeout → retry_exceeded → api_5xx
```

또는:

```text
kafka_lag → consumer_rebalance → processing_timeout
```

이런 짧은 motif를 찾아 incident pattern의 feature로 씁니다.

장점은 운영자에게 설명하기 쉽습니다.

```text
이번 장애는 과거 P3 유형과 유사합니다.
공통 motif: redis_timeout → retry_exceeded → db_pool_wait
```

이 방식은 pattern catalog를 만들 때 좋습니다.

---

# 7. 추천하는 실무형 trajectory clustering 설계

처음부터 복잡한 neural model로 가지 말고, 다음 순서가 좋습니다.

## 1차 baseline

```text
Drain/Spell류 parser 또는 rule parser
→ template_id 생성
→ 5분 window 집계
→ event count vector + metric feature
→ HDBSCAN clustering
→ LLM/운영자 label
```

산출물:

```json
{
  "cluster_id": "INC_PATTERN_007",
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
  }
}
```

## 2차 고도화

```text
incident trajectory sequence
→ DTW distance
→ hierarchical clustering
→ pattern tree 생성
```

이 단계에서 "같은 진행이지만 속도가 다른 장애"를 잘 묶습니다.

## 3차 고도화

```text
sequence encoder
→ contrastive trajectory embedding
→ HDBSCAN
→ nearest incident retrieval
```

이 단계는 과거 incident ticket/RCA가 충분할 때 좋습니다.

---

# 8. Flow Matching과 trajectory clustering의 차이

둘은 문제 정의가 다릅니다.

| 구분       | Trajectory Clustering        | Flow Matching                   |
| -------- | ---------------------------- | ------------------------------- |
| 목적       | 과거 trajectory들을 유사한 유형으로 묶음  | 상태가 시간에 따라 어떻게 이동하는지 학습         |
| 입력       | 관측된 sequence 집합              | source 상태, target 상태, 중간 path   |
| 출력       | cluster label, pattern group | vector field / transition model |
| 질문       | "이 장애는 과거 어떤 유형과 비슷한가?"      | "현재 상태는 앞으로 어디로 흘러갈까?"          |
| 성격       | 분석/분류/검색                     | 생성/예측/동역학 모델링                   |
| 실무 난이도   | 낮음~중간                        | 높음                              |
| 데이터 요구량  | 비교적 적음                       | 많음                              |
| 해석 가능성   | 높음                           | 상대적으로 낮음                        |
| 추천 적용 시점 | 초기부터 가능                      | pattern catalog 이후             |

Flow Matching은 Continuous Normalizing Flow를 simulation-free 방식으로 학습하기 위해 fixed conditional probability path의 vector field를 회귀하는 프레임워크로 제안되었습니다. 즉 본질적으로 "클러스터링 알고리즘"이 아니라 **분포 간 이동을 나타내는 연속시간 vector field를 학습하는 생성모델 방법**입니다. ([arXiv][4])

로그 관점에서 바꾸면:

```text
trajectory clustering:
과거 장애 경로들을 묶는다.

flow matching:
정상 상태 분포에서 장애 상태 분포로 가는 이동장을 학습한다.
```

예를 들어 trajectory clustering은 이런 답을 줍니다.

```text
이번 장애는 Pattern-12와 유사합니다.
Pattern-12는 Redis timeout → retry storm → DB pool exhaustion 유형입니다.
```

Flow matching은 이런 답에 가깝습니다.

```text
현재 상태는 정상 분포에서 Pattern-12 incident manifold 방향으로 이동 중입니다.
예상 경로는 Redis timeout → retry 증가 → DB pool saturation입니다.
```

---

# 9. 둘을 같이 쓰는 방식

둘은 대체재라기보다 단계가 다릅니다.

```text
1. trajectory clustering으로 incident pattern catalog를 만든다.
2. 각 cluster를 "장애 유형"으로 정의한다.
3. flow matching / transition model로 현재 상태가 어느 cluster 방향으로 이동하는지 예측한다.
```

구조적으로는 이렇게 됩니다.

```text
historical incidents
→ trajectory clustering
→ pattern catalog

live logs/metrics
→ current state vector
→ transition/flow model
→ nearest future pattern
→ early warning
```

즉 clustering은 **과거를 정리하는 도구**이고, flow matching은 **현재에서 미래로의 전이를 예측하는 도구**입니다.

---

# 10. 로그 임베딩 설계 상세

실제로 embedding을 만들 때는 raw log text만 넣는 방식은 피하는 게 좋습니다. 추천은 **multi-part embedding**입니다.

## 10.1 Template text embedding

템플릿 문장을 임베딩합니다.

```text
"connection to <*> timed out after <DURATION>"
```

이건 event의 semantic meaning을 담습니다.

하지만 이것만 쓰면 `service`, `dependency`, `severity`, `region` 같은 운영 컨텍스트가 약합니다.

---

## 10.2 Categorical embedding

정규화된 ID들을 embedding합니다.

```text
template_id = redis_timeout
service = checkout-api
dependency = redis
severity = ERROR
region = ap-northeast-2
```

각각을 작은 embedding vector로 둡니다.

```text
e_template
e_service
e_dependency
e_severity
e_region
```

그리고 합치거나 concat합니다.

```text
event_embedding = concat(
  e_template,
  e_service,
  e_dependency,
  e_severity,
  e_region
)
```

---

## 10.3 Numeric feature

수치 parameter도 중요합니다.

```text
duration_ms = 5000
retry_count = 6
status_code = 500
latency_p95 = 1800
error_rate = 0.07
```

이건 normalize해서 붙입니다.

```text
numeric_vector = [
  log1p(duration_ms),
  retry_count,
  status_code_family,
  zscore(latency_p95),
  error_rate
]
```

---

## 10.4 Final event vector

최종 event vector는 이런 형태가 됩니다.

```text
event_vector =
concat(
  text_embedding(template_text),
  categorical_embeddings,
  numeric_features,
  topology_features
)
```

예:

```json
{
  "event_id": "evt_001",
  "template_id": "redis_timeout",
  "template_text": "connection to <*> timed out after <DURATION>",
  "service": "checkout-api",
  "dependency": "redis",
  "severity": "ERROR",
  "numeric": {
    "duration_ms": 5000
  },
  "vector": [0.12, -0.04, 0.88, "..."]
}
```

---

# 11. Window vector 설계 예시

trajectory clustering의 기본 단위는 보통 event가 아니라 window입니다.

예를 들어 5분 window:

```json
{
  "window_start": "2026-06-26T10:00:00",
  "service": "checkout-api",
  "event_counts": {
    "redis_timeout": 42,
    "retry_exceeded": 18,
    "db_pool_wait": 9,
    "api_5xx": 31
  },
  "metrics": {
    "latency_p95": 1850,
    "error_rate": 0.07,
    "cpu": 0.72,
    "memory": 0.81
  }
}
```

이를 벡터로 바꾸면:

```text
x_t = [
  count(redis_timeout),
  count(retry_exceeded),
  count(db_pool_wait),
  count(api_5xx),
  latency_p95_z,
  error_rate_z,
  cpu_z,
  memory_z
]
```

이제 trajectory는:

```text
T_incident = [x_t-6, x_t-5, ..., x_t, ..., x_t+6]
```

입니다.

---

# 12. 어떤 clustering을 선택할까?

상황별 추천은 다음입니다.

| 상황               | 추천                                               |
| ---------------- | ------------------------------------------------ |
| 빠르게 baseline 만들기 | window feature + HDBSCAN                         |
| 장애 속도가 제각각       | DTW + hierarchical clustering                    |
| event 순서가 핵심     | edit distance / LCS sequence clustering          |
| 라벨이 일부 있음        | contrastive sequence encoder                     |
| 운영자 설명 가능성이 중요   | motif/shapelet mining                            |
| 실시간 조기탐지         | trajectory embedding + nearest pattern retrieval |
| 미래 상태 생성/시뮬레이션   | flow matching / neural ODE                       |

초기에는 이 조합이 가장 ROI가 좋습니다.

```text
template extraction
→ 5min window count vector
→ DTW or HDBSCAN
→ cluster label
→ incident pattern catalog
```

---

# 13. 마켓센싱 pipeline과 대응시키면

당신의 market sensing 구조로 비유하면:

| 마켓센싱                  | 로그/장애 분석                       |
| --------------------- | ------------------------------ |
| raw document chunk    | raw log line                   |
| observation candidate | parsed log event               |
| signal candidate      | window-level abnormal pattern  |
| signal                | validated incident signal      |
| claim                 | incident trajectory hypothesis |
| counterclaim          | alternative root cause         |
| clearing              | RCA validation / postmortem    |
| outlook claim         | future degradation prediction  |

trajectory clustering은 여기서:

```text
signal candidate들이 시간순으로 모인 incident claim pattern을 그룹화하는 작업
```

에 해당합니다.

Flow matching은:

```text
현재 signal state가 어떤 incident claim pattern으로 진행될지 예측하는 동역학 모델
```

에 가깝습니다.

---

# 14. 최종 정리

**템플릿 추출**은 raw log를 다음처럼 바꾸는 일입니다.

```text
"connection to redis-01 timed out after 3000ms"
→ "connection to <*> timed out after <DURATION>"
→ template_id = redis_timeout
```

**임베딩화**는 이 event를 벡터로 만드는 일입니다.

```text
template text + service + dependency + severity + numeric parameter
→ event vector
```

**trajectory clustering**은 event/window sequence를 묶는 일입니다.

```text
redis_timeout → retry_exceeded → db_pool_wait → api_5xx
```

같은 진행 경로를 하나의 incident pattern으로 묶습니다.

**flow matching**은 clustering이 아니라, 상태 전이를 학습하는 모델입니다.

```text
normal state → degraded state → incident state
```

로 흘러가는 vector field를 배웁니다.

따라서 실무 적용 순서는 이게 좋습니다.

```text
1. 로그 템플릿 추출
2. event/entity 정규화
3. event/window embedding
4. trajectory clustering
5. incident pattern catalog 구축
6. 이후 필요하면 flow matching으로 조기 예측/trajectory generation 확장
```

결론적으로, **로그 오류 패턴 유형화의 본체는 trajectory clustering이고, flow matching은 그 다음 단계의 "장애 전이 예측/생성 모델"로 붙이는 게 맞습니다.**

---

## 참고문헌

[1]: https://ieeexplore.ieee.org/document/8029742/ "Drain: An Online Log Parsing Approach with Fixed Depth Tree"
[2]: https://users.cs.utah.edu/~lifeifei/papers/spell.pdf "Spell: Streaming Parsing of System Event Logs"
[3]: https://arxiv.org/abs/1810.12722 "Feature Trajectory Dynamic Time Warping for Clustering of Speech Signals"
[4]: https://arxiv.org/abs/2210.02747 "Flow Matching for Generative Modeling"
