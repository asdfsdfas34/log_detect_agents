# AIOps / PatternOps 시각화

작성일: 2026-07-03

이 문서는 FastAPI + LangGraph 기반 로그 탐지 백엔드와 PatternOps Registry,
embedding/유사도, time-window 상태 벡터, baseline/RecFM 논의 내용을 시각적으로
정리한 자료입니다.

## 1. 전체 시스템 맵

```mermaid
flowchart TB
  subgraph Client["사용자 / 외부 시스템"]
    FE["Frontend"]
    API["FastAPI API"]
  end

  subgraph Runtime["LangGraph Runtime"]
    ORCH["OrchestratorAgent"]
    COL["LogCollectorAgent"]
    ANA["LogAnalysisAgent"]
    ANO["AnomalyDetectionAgent"]
    RAG["KnowledgeBaseRAGAgent"]
    REC["RecommendationAgent"]
    RULE["PatternRuleSuggestionAgent"]
  end

  subgraph PatternOps["PatternOps / SkillOps-style Registry"]
    SKILL["pattern_skills"]
    EDGE["pattern_skill_edges"]
    EXEC["pattern_skill_executions"]
    CONTRACT["pattern_contracts"]
    ACTION["pattern_ops_actions"]
  end

  subgraph Storage["Storage"]
    PG["PostgreSQL<br/>structured data"]
    CHROMA["ChromaDB<br/>vector search"]
  end

  FE --> API
  API --> ORCH
  ORCH --> COL
  COL --> ANA
  ANA --> ANO
  ANO --> RAG
  RAG --> REC
  RULE --> ANA

  ANA --> PatternOps
  ANO --> PatternOps
  REC --> PatternOps
  PatternOps --> PG

  ANA --> CHROMA
  RAG --> CHROMA
  REC --> CHROMA
  API --> FE
```

## 2. `/analyze` 실행 흐름

```mermaid
sequenceDiagram
  actor User as 사용자
  participant API as FastAPI<br/>POST /analyze
  participant Graph as LangGraph Engine
  participant O as OrchestratorAgent
  participant C as LogCollectorAgent
  participant L as LogAnalysisAgent
  participant A as AnomalyDetectionAgent
  participant S as Scenario Detection
  participant P as PatternOps Registry
  participant R as KnowledgeBaseRAGAgent

  User->>API: 분석 요청
  API->>Graph: graph 실행
  Graph->>O: 다음 worker 결정
  O->>C: 로그 수집
  C-->>O: normalized_logs
  O->>L: 로그 분석
  L-->>O: fingerprint, known/new, matches
  O->>A: anomaly 탐지
  A-->>O: anomalies, daily counts
  O-->>Graph: END
  Graph->>S: scenario detection pipeline
  S->>P: skill plan / execution 기록
  P->>R: 관련 지식 조회
  R-->>API: AnalyzeResponse 구성
  API-->>User: 분석 결과
```

## 3. 개념적 Agent와 현재 구현 매핑

```mermaid
flowchart LR
  subgraph Concept["개념적 Agent"]
    C1["Collector / Normalizer"]
    C2["Fingerprint Agent"]
    C3["Pattern Agent"]
    C4["Anomaly Agent"]
    C5["Recommendation Agent"]
    C6["Feedback / Memory Agent"]
  end

  subgraph Impl["현재 구현"]
    I1["LogCollectorAgent"]
    I2["LogAnalysisAgent"]
    I3["scenario_store"]
    I4["AnomalyDetectionAgent"]
    I5["RecommendationAgent"]
    I6["승인 / 예외 / Knowledge Card API"]
  end

  C1 --> I1
  C1 --> I2
  C2 --> I2
  C2 --> I3
  C3 --> I2
  C3 --> I3
  C4 --> I4
  C5 --> I5
  C6 --> I6
```

## 4. PatternOps Skill Graph

```mermaid
flowchart TD
  LC["log_collection"] --> LN["log_normalization"]
  LN --> PF["pattern_fingerprint"]
  PF --> KM["known_pattern_match"]
  PF --> DD["duplicate_pattern_detection"]
  DD --> FM["fingerprint_merge"]

  KM --> AD["anomaly_detection"]
  KM --> KR["knowledge_card_retrieval"]
  KM --> CR["chroma_similar_pattern_retrieval"]

  AD --> RG["recommendation_generation"]
  KR --> RG
  CR --> RG
  RG --> QG["recommendation_quality_gate"]
  QG --> RC["resolution_capture"]

  PR["pattern_rule_suggestion"] --> LN
  EX["exception_suppression"] --> AD

  classDef meta fill:#f8fafc,stroke:#64748b,color:#0f172a
  classDef runtime fill:#ecfeff,stroke:#0891b2,color:#164e63
  classDef memory fill:#f0fdf4,stroke:#16a34a,color:#14532d

  class LN,PF,KM,DD meta
  class LC,AD,RG,QG,PR runtime
  class KR,CR,RC,FM,EX memory
```

## 5. Skill 내부 계약 구조

```mermaid
flowchart LR
  REQ["Precondition<br/>requires"] --> OP["Operation<br/>operation_ref"]
  OP --> OUT["Artifact<br/>produces"]
  OUT --> VAL["Validator<br/>checks"]
  VAL --> EXEC["Execution Record<br/>pattern_skill_executions"]
  EXEC --> AUDIT["Auditable Action<br/>pattern_ops_actions"]
```

## 6. PatternOps Registry 데이터 모델

```mermaid
erDiagram
  pattern_skills ||--o{ pattern_skill_edges : connects
  pattern_skills ||--o{ pattern_skill_executions : records
  pattern_contracts ||--o{ pattern_contract_edges : relates
  pattern_contracts ||--o{ pattern_contract_validators : validates
  pattern_contracts ||--o{ pattern_ops_actions : audits
  pattern_skills ||--o{ pattern_ops_actions : maintains

  pattern_skills {
    string skill_id
    string operation_ref
    json requires
    json produces
    json validators
  }

  pattern_skill_executions {
    string request_id
    string skill_id
    string status
    json evidence
  }

  pattern_contracts {
    string contract_id
    string pattern_type
    string fingerprint
    string status
  }

  pattern_ops_actions {
    string action_id
    string action_type
    string actor
    datetime created_at
  }
```

## 7. Embedding / Similarity 구조

```mermaid
flowchart TB
  subgraph Inputs["Embedding 입력"]
    TPL["Pattern / Fingerprint cluster<br/>service + fingerprint + context"]
    CARD["Knowledge Card<br/>승인된 Case Card 문서"]
    KNOWN["Known Pattern<br/>원인 + 조치 + evidence"]
    INC["Incident Summary<br/>incident analysis 문서"]
  end

  MODEL["text-embedding-3-large"]

  subgraph Collections["ChromaDB Collections"]
    C1["pattern_templates_v2<br/>1024 dim"]
    C2["case_cards_v2<br/>1536 dim"]
    C3["known_patterns_v2<br/>1536 dim"]
    C4["incident_summaries_v2<br/>1536 dim"]
  end

  subgraph Decision["Similarity 활용"]
    S1["Known similar pattern<br/>threshold 0.88"]
    S2["Duplicate semantic candidate<br/>threshold 0.93"]
    S3["Recommendation / RAG evidence"]
  end

  TPL --> MODEL
  CARD --> MODEL
  KNOWN --> MODEL
  INC --> MODEL

  MODEL --> C1
  MODEL --> C2
  MODEL --> C3
  MODEL --> C4

  C1 --> S1
  C1 --> S2
  C2 --> S3
  C3 --> S3
  C4 --> S3
```

## 8. Time Window와 System State Vector

```mermaid
flowchart LR
  LOG["service_logs"] --> FP["fingerprint 집계"]
  FP --> METRIC["pattern_time_series_metrics<br/>hour / day"]
  METRIC --> WIN["event_time_windows"]
  WIN --> VEC["system_state_vectors<br/>10차원 numeric vector"]
  VEC --> LABEL["label<br/>normal / warning / incident"]
```

```mermaid
flowchart TB
  subgraph Vector["10차원 State Vector"]
    F1["total_events"]
    F2["error_ratio"]
    F3["warn_ratio"]
    F4["info_ratio"]
    F5["unique_fingerprint_count"]
    F6["unique_fingerprint_ratio"]
    F7["known_fingerprint_ratio"]
    F8["new_fingerprint_ratio"]
    F9["anomaly_count"]
    F10["max_risk_score / 100"]
  end

  subgraph Label["Label 규칙"]
    L1["anomaly_count > 0<br/>incident"]
    L2["max_risk_score >= 70<br/>warning"]
    L3["otherwise<br/>normal"]
  end

  Vector --> Label
```

## 9. Baseline 예측 모델

```mermaid
flowchart LR
  V5["t-5h vector"] --> B["baseline model"]
  V4["t-4h vector"] --> B
  V3["t-3h vector"] --> B
  V2["t-2h vector"] --> B
  V1["t-1h vector"] --> B
  B --> P["t+1h 상태 예측<br/>normal / warning / incident"]

  subgraph Candidates["가능한 baseline"]
    R["Rule-based"]
    LR["Logistic Regression"]
    RF["Random Forest / XGBoost"]
    EWMA["Moving Average / EWMA"]
    RNN["GRU / LSTM"]
  end

  Candidates -. "후보 모델" .-> B
```

## 10. 현재 상태와 향후 Trajectory Modeling

```mermaid
flowchart LR
  subgraph Now["현재 존재"]
    N1["log parsing / template extraction"]
    N2["embedding"]
    N3["clustering / similarity search"]
    N4["incident pattern catalog"]
    N5["time-window aggregation"]
    N6["system state vector generation"]
  end

  subgraph Next["현실적인 다음 단계"]
    X1["state vector 수집 지속"]
    X2["dataset builder"]
    X3["최근 N시간 baseline"]
    X4["t+1h 상태 예측"]
    X5["feature 예측력 평가"]
    X6["필요 시 multi-scale window 추가"]
  end

  subgraph Later["나중에 검토"]
    L1["trajectory dataset"]
    L2["RecFM model class"]
    L3["training loop"]
    L4["forecast API"]
    L5["future trajectory result table"]
    L6["recursive consistency logic"]
  end

  Now --> Next --> Later
```

## 11. 점진적 진행 로드맵

```mermaid
gantt
  title AIOps / PatternOps Trajectory Modeling Roadmap
  dateFormat  YYYY-MM-DD
  axisFormat  %m/%d

  section Data Foundation
  hour/day state vector 수집          :active, a1, 2026-07-03, 14d
  system_state_vectors dataset builder :a2, after a1, 7d

  section Baseline
  최근 N시간 window baseline           :b1, after a2, 7d
  t+1h 상태 예측 API 검토              :b2, after b1, 7d
  feature 예측력 평가                  :b3, after b2, 7d

  section Expansion
  30분/2시간/3시간 multi-scale window  :c1, after b3, 10d
  충분한 labeled trajectory 축적       :c2, after c1, 21d

  section Research
  RecFM 적용 가능성 검토               :d1, after c2, 14d
```
