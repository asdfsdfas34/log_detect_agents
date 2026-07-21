# LogDetect PoC 핵심 기술 과제 최종 보고

## Key Message

정규화를 일회성 전처리에서 **운영자 승인 기반 학습 루프**로 전환해, 동일 장애의 50개 로그 변형을 1개 Fingerprint로 수렴시키고 승인 지식을 재사용했다.

## 핵심기술난제

request ID·경로·숫자 같은 변동값은 동일 장애를 여러 Fingerprint로 분산시키며, 고정 정규식은 운영 중 발생하는 신규 변형을 스스로 흡수하지 못한다.  
핵심 난제는 정규화 결과를 검증·축적·재사용하는 장기 운영 학습 레이어로 전환하는 것이었다.

## 어떻게 해결했는가? (설계 결정)

결정적 정규화 후 구조·의미 근거로 중복 후보를 생성하되, 운영자 승인 시에만 rule·canonical alias·Known Pattern을 영속화했다.  
승인 지식을 다음 분석에 재적용하는 **후보 생성 → 검증 → 지식화 → 재사용**의 Human-in-the-loop 폐루프를 설계했다.

## 핵심 알고리즘

정규화·Fingerprint → token/구조/stack trace/embedding 가중 유사도 → connected component/HDBSCAN 군집화를 적용하고, embedding 실패 시 Drain3 template으로 전환한다.

## 아키텍처 결정

LangGraph `SharedState`가 Agent 흐름을 조율하고, 승인 지식은 SQLite의 rule·alias·Known Pattern과 PatternOps contract에 저장하며 ChromaDB RAG와 MCP-style registry로 검색·도구 경계를 분리한다.

## 핵심 기술 선택 이유

| 기술 선택 | 적용 이유와 방식 |
|---|---|
| Deterministic + Hybrid Matching | 재현 가능한 Fingerprint를 기준으로 구조·의미 유사도를 보강해 embedding 단독 오병합을 제한했다. |
| LangGraph + SharedState | Agent별 실행·재시도·실패를 공통 상태로 추적하고 가능한 분석은 계속하는 graceful degradation을 구현했다. |
| PatternOps + SQLite/ChromaDB | 승인 규칙은 구조화 지식으로, Knowledge Card는 검색 지식으로 분리해 판정과 권고에 재사용했다. |

## 왜 이 접근이 필요했는가?

정규식만 사용하면 새 변형을 놓치고, embedding만 사용하면 의미는 비슷하지만 장애 구조가 다른 로그까지 합칠 수 있다.  
결정적 기준·다중 근거·운영자 승인을 결합해야 재현성, 오탐 통제, 운영 지식의 감사 가능성을 함께 확보할 수 있다.

## 성과지표

| 지표 | 평가 데이터·산식 | 검증 결과 |
|---|---|---:|
| Fingerprint 수렴률 | 동일 패턴 변형 50건, `1-(통합 후 FP/통합 전 FP)` | **50→1, 98%** |
| Known Pattern 재사용률 | 승인에 미사용한 신규 변형 50건, `Known 판정/전체 변형` | **50/50, 100%** |
| 증분 처리 절감률 | 신규 로그 50건 재분석, `1-(재처리/최초 처리)` | **50→0, 100%** |

> 표시된 KPI 3개 150건과 신규 이상 식별 50건을 격리 DB에서 검증했으며, KPI 테스트는 `4 passed`로 통과했다.

## 검증 범위 및 다음 단계

현재 수치는 합성 fixture 기반 기술 검증 결과로 운영 로그 전체의 정확도나 처리시간을 의미하지 않는다.  
후속 단계에서는 실제 라벨 로그와 negative control을 확보해 오병합률·재현율·처리 지연을 함께 측정한다.

## 기술 근거

- He et al., 2017, [Drain: An Online Log Parsing Approach with Fixed Depth Tree](https://doi.org/10.1109/ICWS.2017.13)
- McInnes et al., 2017, [hdbscan: Hierarchical Density Based Clustering](https://doi.org/10.21105/joss.00205)
- Lewis et al., 2020, [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://papers.nips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)
