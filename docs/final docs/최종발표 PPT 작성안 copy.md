# AI Master Project 최종발표 PPT 작성안

## 1페이지 — 표지

### LogDetect: 운영 로그 분석·지식화 Mini-AIOps

- **과제명:** 패턴 학습 기반 운영 로그 분석 및 대응 지식화 시스템
- **멘티:** [성명], [사번]
- **멘토:** [성명1], [성명2]

---

## 2페이지 — 프로젝트 개요

### 문제 정의

배포 후·정기 점검마다 운영자가 대량 로그를 직접 확인해 최대 30분 이상이 소요되고, 개인이 체득한 장애 판단과 조치 경험은 재사용 가능한 지식으로 남지 않는다.  
반복 점검을 자동화하고 검증된 결과를 조직의 운영 지식으로 전환하는 것이 목표다.

### 핵심 기능

`OrchestratorAgent → LogCollectorAgent → LogAnalysisAgent → AnomalyDetectionAgent → KnowledgeBaseRAGAgent → RecommendationAgent` 흐름으로 로그 수집·정규화·패턴 판정·이상 탐지·유사 사례 검색·대응 권고를 수행한다.  
**기술 스택:** FastAPI · LangGraph · MCP-style Tool Registry · SQLite · ChromaDB · RAG · OpenAI/Azure OpenAI Embeddings · Vue 3 · TypeScript

### 핵심 성과

| 성과 | 정성적 성과 | 정량적 성과지표 |
|---|---|---:|
| **지식 축적** | 승인된 규칙·Known Pattern을 다음 분석에 재사용 | 신규 변형 **50/50건 재인식(100%)** |
| **점검 시간 감소** | 로그 전수 확인을 자동 분석·검토 중심으로 전환 | **약 30분→5분 이하 목표(~83% 감소, 실측 예정)** |
| **패턴 인식 향상** | 변동값이 다른 동일 장애의 분산·중복을 축소 | **50개→1개 Fingerprint 수렴(98%)** |

### Key Message

> 로그 점검을 자동화하고, 운영자 검증 결과를 다음 분석에 재사용하는 지속 학습형 운영 지식으로 전환했습니다.

---

## 3페이지 — 기술 아키텍처

![LogDetect 최종 기술 아키텍처](</Users/a10068/Desktop/log_detect_agents/docs/final docs/최종아키텍처.png>)

### 아키텍처 흐름

Vue 3 대시보드가 FastAPI의 REST·SSE API로 분석을 요청하고, LangGraph가 `Orchestrator → 로그 수집 → 로그 분석 → 이상 탐지` 흐름과 `SharedState`를 관리한다.  
FastAPI 서비스 흐름은 Knowledge RAG·추천 생성·PatternOps·패턴 운영을 결합하며, 데이터 접근 계층을 통해 SQLite·ChromaDB·OpenAI와 연결된다.

### 핵심 기술 선택 1 — Deterministic 정규화 + PatternOps Registry

변동값으로 동일 장애가 여러 패턴으로 분리되는 문제를 막기 위해 결정적 Fingerprint를 기준으로 사용했다. 운영자가 승인한 rule·alias·Known Pattern을 저장해 이후 Known/New 판정과 원인·조치 근거에 재사용한다.

### 핵심 기술 선택 2 — Knowledge Card RAG + Recommendation Quality Gate

모델 재학습 없이 축적 장애 사례를 활용하기 위해 ChromaDB에서 Knowledge Card를 검색한다. 생성 권고는 품질 점수와 hard-fail 조건으로 검증하고, 실패 시 재생성 또는 deterministic fallback을 수행한다.

### 핵심 기술 선택 3 — LangGraph Multi-Agent Orchestration

조건부 실행·상태 분기·재시도·실패 이력을 관리하기 위해 LangGraph와 `SharedState`를 적용했다. 기본 분석과 선택 Fingerprint의 상세 권고를 분리해 불필요한 LLM 호출과 자동 저장을 방지한다.

---

## 4페이지 — 핵심 기술 과제

### 핵심 기술 난제

request ID·경로·숫자 같은 변동값 때문에 동일 장애가 여러 Fingerprint로 분산되며, 고정 정규식은 신규 변형을 지속 흡수하지 못한다.  
정규화를 일회성 전처리가 아닌 **검증·축적·재사용 가능한 운영 학습 레이어**로 전환해야 했다.

### 엔지니어링 접근 방법
정규화와 Fingerprint를 1차 기준으로 두고, Drain3·hybrid similarity·HDBSCAN으로 중복 후보를 만든 뒤 운영자 승인 시 normalization rule, canonical Fingerprint alias, Known Pattern을 함께 저장하도록 설계하여
“Human-in-the-loop 기반 지속 학습형 운영 메모리”를 사용한다.

### 핵심 알고리즘
정규화 후 Drain3·hybrid similarity·HDBSCAN으로 중복 후보를 만들고, 승인된 rule·alias·Known Pattern을 저장했다. 

LangGraph와 PatternOps가 이를 다음 분석에 재적용하는 “Human-in-the-loop 운영 메모리”를 구성했다.은 SQLite·PatternOps에 저장하며 ChromaDB RAG와 MCP-style registry로 검색·도구 경계를 분리한다.

### 왜 이 접근이 필요한가?
정규식만으로는 새 변형을 놓치고, embedding만으로는 구조가 다른 로그를 잘못 합칠 수 있다. 
결정적 규칙·다중 근거·운영자 승인을 결합해 재현성과 오탐 통제를 확보했다.

### 결과 및 성과

| 성과지표 | 평가 조건 | 결과 |
|---|---|---:|
| **Fingerprint 수렴률** | 복 후보 Fingerprint 수렴 정확도 |동일 패턴 변형 50건 | **50→1, 98%** |
| **Known Pattern 재사용률** | 승인에 미사용한 신규 변형 50건 | **50/50, 100%** |
| **증분 처리 절감률** | 신규 로그 50건 동일 조건 재분석 | **50→0, 100%** |

> KPI별 합성 데이터 50건씩 총 150건을 격리 DB에서 검증했으며, KPI 테스트는 `3 passed`로 통과했다. 점검시간 감소는 목표값으로, 10회 이상 실측 후 확정한다.

### 기술 근거

- He et al., 2017, [Drain: An Online Log Parsing Approach with Fixed Depth Tree](https://doi.org/10.1109/ICWS.2017.13)
- McInnes et al., 2017, [hdbscan: Hierarchical Density Based Clustering](https://doi.org/10.21105/joss.00205)
- Lewis et al., 2020, [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://papers.nips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)
