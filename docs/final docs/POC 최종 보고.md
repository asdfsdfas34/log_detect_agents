# LogDetect PoC 최종 보고

## 핵심기술난제

request ID·경로·숫자 등의 변동값 때문에 동일 장애가 여러 Fingerprint로 분산되고, 고정 정규식은 새 변형을 지속 흡수하기 어렵다.  
따라서 운영자 검증 결과를 다음 분석에 재사용하는 장기 운영 학습 레이어가 필요했다.

## 어떻게 해결했는가? (설계 결정)

결정적 정규화 후 Drain3·hybrid similarity·HDBSCAN으로 중복 후보를 만들고, 승인된 rule·alias·Known Pattern을 저장했다.  
LangGraph와 PatternOps가 이를 다음 분석에 재적용하는 **Human-in-the-loop 운영 메모리**를 구성했다.

## 핵심 알고리즘

변동값 정규화와 Fingerprint 생성 후 다중 가중 유사도·connected component·HDBSCAN으로 중복을 군집화하고, embedding 실패 시 Drain3로 전환한다.

## 아키텍처 결정

LangGraph가 `SharedState`로 분석을 조율하고, 승인 결과를 SQLite·PatternOps에 축적해 재사용하며 ChromaDB RAG와 MCP-style registry로 검색·호출 경계를 분리한다.

## 왜 이 접근이 필요했는가?

정규식만으로는 새 변형을 놓치고, embedding만으로는 구조가 다른 로그를 잘못 합칠 수 있다.  
결정적 규칙·다중 근거·운영자 승인을 결합해 재현성과 오탐 통제를 확보했다.

## 성과지표

| 지표 | 검증 결과 |
|---|---|
| Fingerprint 수렴 | 3개를 canonical 1개로 통합해 **66.7% 축소**, occurrence **100% 보존** |
| 규칙 재사용 | 신규 변형 3건을 **3/3(100%) Known Pattern**으로 흡수 |
| 증분 분석 | 재실행 시 신규 처리 **1건 → 0건**, 중복 재처리 **100% 제거** |

> 고정 fixture 기반 PoC 결과이며 운영 benchmark는 아니다. 핵심 테스트는 `3 passed`로 통과했다.

## 기술 근거

- He et al., 2017, [Drain: An Online Log Parsing Approach with Fixed Depth Tree](https://doi.org/10.1109/ICWS.2017.13)
- McInnes et al., 2017, [hdbscan: Hierarchical Density Based Clustering](https://doi.org/10.21105/joss.00205)
- Lewis et al., 2020, [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://papers.nips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)
