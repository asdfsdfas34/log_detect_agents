# LogDetect PoC 최종 보고

## 핵심기술난제

request ID·경로·숫자처럼 계속 변하는 값 때문에 동일 장애가 서로 다른 Fingerprint로 분산되며, 고정 정규식만으로는 운영 중 새 변형을 지속 흡수하기 어렵다.  
따라서 정규화를 일회성 전처리가 아니라, 운영자 검증 결과가 다음 분석의 판정 기준으로 환류되는 장기 운영 학습 레이어로 전환해야 했다.

## 어떻게 해결했는가? (설계 결정)

결정적 정규화와 Fingerprint를 1차 기준으로 두고, Drain3·hybrid similarity·HDBSCAN으로 중복 후보를 만든 뒤 운영자 승인 시 normalization rule, canonical Fingerprint alias, Known Pattern을 함께 저장하도록 설계했다.  
LangGraph의 **Planning → Execution → Verification → Memory Update** 흐름과 PatternOps Registry가 승인 지식을 다음 분석에 재적용하므로, 이는 모델 재학습이 아닌 **Human-in-the-loop 기반 지속 학습형 운영 메모리**다.

## 핵심 알고리즘 / 아키텍처 결정

정규식 치환 → 해시 Fingerprint → Drain template → 구조·token·stack trace·embedding 가중 유사도 → connected component/HDBSCAN 순으로 후보를 좁혀, 의미 유사도만 높은 오탐 병합을 차단했다. 
승인 결과는 SQLite의 rule/alias/Known Pattern 및 PatternOps contract로 버전 가능한 지식이 되고, Knowledge Card는 ChromaDB RAG로 권고에 재사용한다
관련 근거는 
[Drain (He et al., 2017)](https://doi.org/10.1109/ICWS.2017.13), [HDBSCAN (McInnes et al., 2017)](https://doi.org/10.21105/joss.00205)이다. 
([Lewis et al., 2020](https://papers.nips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)).

## 왜 이 접근이 필요했는가?

정규식만 사용하면 새 로그 변형을 놓치고, embedding만 사용하면 문장 의미는 비슷하지만 장애 구조가 다른 로그까지 합칠 수 있다.  
결정적 규칙·다중 근거 군집·사람의 승인을 결합해야 재현성, 오탐 통제, 운영 지식의 누적과 감사 가능성을 동시에 확보할 수 있다.

## 성과지표

| 지표 | 검증 결과 |
|---|---|
| Fingerprint 수렴·보존 | 승인 전 3개 Fingerprint를 canonical 1개로 통합해 **66.7% 축소**, occurrence 3건은 **100% 보존** |
| 학습 규칙 재사용 | 기존 canonical과 다른 신규 원문 변형 3건을 **3/3(100%) Known Pattern**으로 흡수하고 Fingerprint 1개로 집계 |
| 증분 분석 효율 | 동일 조건 재실행 시 `processed_new_logs`가 **1건 → 0건**으로 감소해 중복 재처리 **100% 제거**, occurrence는 1건으로 유지 |

> 위 수치는 격리된 고정 fixture 회귀 테스트의 PoC 결과이며 운영 정확도·처리시간 benchmark는 아니다. 핵심 3개 테스트는 2026-07-15 기준 `3 passed, 50 deselected`로 통과했다.
