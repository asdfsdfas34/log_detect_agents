



SK_AI Talent Lab 검색





홈
1

DM
2

내 활동
3

파일
4

더 보기
0

SK_AI Talent Lab


대화 찾기…






6





메시지

캔버스리스트폴더
0_master-project_6기_이재영m
@서동위 님이 날짜: 5월 28일에 이 채널을 생성했습니다. 0_master-project_6기_이재영m 채널의 맨 첫 부분입니다.

채널에 사람 추가

다양한 사람들의 아바타

채널 설명 추가

‘설명’으로 어떤 채널인지 읽어보세요.

템플릿 선택

이 채널의 템플릿을 선택하세요
서동위
  오후 6:22
0_master-project_6기_이재영m에 참여했습니다. 또한 초대를 통해 이재영
 님 및 4명의 다른 사용자가 참여했습니다.
이재영
  오전 11:19
[6/12 2회차 정기 멘토링 세션]  에서는 아래의 내용을 다뤘습니다.
요건+기술 요소 mixup 설계 + code 스니펫 + 새로운 트랜드를 통한 해결
더 깊이, 더 쌓되 구조적으로 (chatgpt dreaming)
You can outsource your thinking but you can’t outsource your understanding.
5월 5주차 main keyword - Test-time loop scaling ( backed by [quality verification + long-horizon stability] )
reasoning RAG
Ptah + DocSeeker
harness_evolution (harness making 과 harness execution 분리)
Google Sufficient Context Agent  https://discuss.pytorch.kr/t/google-research-agentic-rag/10599
기획 feedback
차주 3회차 정기 멘토링 세션은 6/17 수요일 오후 13시 30분(본사 701호 회의실)입니다. (편집됨) 
정선웅
  오전 10:19
0_master-project_6기_이재영m에서 나갔습니다. 또한, 초대를 통해 정선웅
 님이 참여했습니다.
정선웅
  오전 10:19
반갑습니다
이재영
  오후 1:48
[6/26 정기 멘토링 세션] 에서는 아래의 내용을 다뤘습니다.
 차주 정기 멘토링은 7/3(금) 오전 10시 본사 703호 입니다.
The harder human capital problem - 인적 자본과 토큰 자본이 서로를 키운다?
pattern - markdown artifact (2주차 agent > 5번 항목 바로 아래)
Skill - 스킬 생성, 스킬 사용 최적화(skillopt), 스킬 관리 (skillops), 스킬 토큰 최적화 (skillMoo)
설계 리뷰 & feedback
market sensing Agent (추적 가능성, 청산 가능성)
Mini-AIOps
log parsing/template extraction -> embedding -> clustering -> incident pattern catalog
event -> time-window aggrigation 과 시스템 상태 백터로 trajectory modeling 가능
recursive Flow Matching (RecFM)
Agent 역할 구분 및 workflow 생성 - 현재는 로그분석자동화 pipeline + rag 입니다.  관찰을 쌓고, 지식화하는 과정의 workflow 흐름이 보이면 좋겠습니다.
| Agent                 | 역할                    |
| --------------------- | --------------------- |
| Collector/Normalizer  | 로그 수집·정규화             |
| Fingerprint Agent     | 템플릿화·중복 집계            |
| Pattern Agent         | Known/New 분류          |
| Anomaly Agent         | spike/new/silence 탐지  |
| Recommendation Agent  | RAG 기반 원인/조치 후보 생성    |
| Feedback/Memory Agent | 승인·반려·예외·Case Card 등록 |
PatternOps Registry(skillOpt 차용) https://github.com/Hik289/SkillOps
로그/에러/대응 패턴을 운영 가능한 지식 자산으로 관리하는 Ops 레이어로 변환하는 게 핵심
Known Pattern Registry가 커질수록 생기는 기술부채를 관리할 수 있습니다.
Registry Maintenance Loop를 만들 수 있습니다.  실시간 탐지 루프와 지식관리 루프를 분리
Smart WMS Agent
가장 사용자와 맞닿아있는 복합 질의 분해 성능이 이후의 모든것을 가를 수 있음
Verifier 구체화 필요 : Tool 출력 형식, WMS 정책, 답변 근거
Blackboard 기반 운영 상황판 구조 도임 검토
각 specialist agents가 결과를 Blackboard에 올리고, Aggregator가 우선순위를 결정 (+Priority Score 표준화 필요)
핵심은 공유 메모리가 아닌 공유 상태 - 상태 모델링(State Modeling) 이후 모든 특화 에이전트는 상태만 변경
                WarehouseBoard
        (공유 Operational State)
                      │
     ┌────────────────┼────────────────┐
     │                                               │                                               │
Picking Agent                   Inventory Agent                     Stocking Agent
     │                                               │                                               │
     └────────────────┼────────────────┘
                      │
              Priority Aggregator
                      │
               Planner / Scheduler
                      │
             Draft → Dry Run → Approval
                      │
                   Execute (편집됨) 
이재영
  오전 9:39
@신희승
log_trajectory_clustering_guide.md
 

log_trajectory_clustering_guide.md
Markdown
로그 오류 패턴 유형화 설계 가이드
가능한 설계 흐름은 이렇게 잡는 게 가장 좋습니다.




9:40
agentic-ai-patterns-guide.md
 

agentic-ai-patterns-guide.md
Markdown
에이전틱 AI 패턴 완벽 가이드 (v3)
핵심 통찰: 에이전트 시스템은 Design-Time 패턴(어떻게 생각하고 실행할 것인가)과 Runtime 패턴(어떻게 신뢰성 있게 운영할 것인가)의 조합이다.

“Reliability is not a model property. It is an engineering problem.”




이재영
  오후 2:28
[7/3 정기 멘토링 세션] 에서는 아래의 내용을 다뤘습니다.
 차주 정기 멘토링은 7/10(금) 오전 10시 본사 703호 입니다.
agent의 숨겨진, 그러나 품질에 결정적인 인프라 - 검색과 저장
어떻게 잘 검색하고, 이를 위해 어떻게 저장하는게 좋은가? (다음주는 검색입니다)
The Harness Is Commoditized.
경쟁지점은 이제 실행이 아닌 판단재료
무엇을 할 수 있는지? (harness) 무엇을 해야 하는지? (Context layer)
장기적으로 남는 자산은 결국 context layer, harness 밖에 두자
결국 또 skill 화 된 Memory를 어떻게 저장하고 어떻게 가져오느냐의 문제
그 과정에서 외부에 도구화 된 메모리를 하네스 내부로 들고오는 protocol = mcp, skill
3. 트렌드 소개 - 쪼개기, 구조화
Compositional Skill Routing for LLM Agents: Decompose, Retrieve, and Compose
AtomMem: Building Simple and Effective Memory System for LLM Agents via Atomic Facts
4. 설계 리뷰 & feedback
market sensing Agent ( chunk에서 증거추출 후 원자 단위로 쪼개기-> 분석 ontology (어떻게 저장) -> 신호 (복합 키 groupby) 어떻게 검색해서 -> 주장 -> 주장 ontology 어떻게 쌓아둘지)
Mini-AIOps (패턴 정규화 effort 는 좋은 방향, 단 임베딩 후 clustering 알고리즘 비교 및 최적화 필요 + 패턴화에서 한번더 llm 에 걸어서 이유를 달아보는것도 좋을 듯)
WOONG AI (앜ㅋㅋㅋ 이름!, 제약하 최적화 문제, FIFO는 알고리즘인가, 블랙보드 핵심은 오케스트레이터의 최적배분!, 돌발상황 triggering & rescheduling?)
(편집됨)












0_master-project_6기_이재영m에 메시지 보내기









Shift + Enter 키를 눌러 새 행을 추가합니다




:종:
Slack은 고객이 허용해야 알림을 활성화할 수 있습니다. 알림 활성화

에이전틱 AI 패턴 완벽 가이드 (v3)
핵심 통찰: 에이전트 시스템은 Design-Time 패턴(어떻게 생각하고 실행할 것인가)과 Runtime 패턴(어떻게 신뢰성 있게 운영할 것인가)의 조합이다.

“Reliability is not a model property. It is an engineering problem.” — Vasundra Srinivasan, AI Council 2026

📊 통합 아키텍처 Overview
┌─────────────────────────────────────────────────────────────────────┐
│                     에이전틱 AI 아키텍처                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │              DESIGN-TIME PATTERNS (설계 시점)                  │  │
│  │                 "어떻게 생각하고 실행할 것인가?"                │  │
│  │                                                               │  │
│  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │  │
│  │   │  Thinking   │  │  Execution  │  │Coordination │          │  │
│  │   │   (인지)    │  │   (실행)    │  │   (조정)    │          │  │
│  │   └─────────────┘  └─────────────┘  └─────────────┘          │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │               RUNTIME PATTERNS (운영 시점)                     │  │
│  │                "어떻게 신뢰성 있게 운영할 것인가?"              │  │
│  │                                                               │  │
│  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │  │
│  │   │    State    │  │   Control   │  │    Saga     │          │  │
│  │   │   (상태)    │  │   (제어)    │  │   (보상)    │          │  │
│  │   └─────────────┘  └─────────────┘  └─────────────┘          │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                              ▼                                      │
│  ┌───────────────────────────────────────────────────────────────┐  │
│  │                 INFRASTRUCTURE (인프라)                        │  │
│  │                                                               │  │
│  │   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐          │  │
│  │   │   Memory    │  │   Runtime   │  │  Observtic  │          │  │
│  │   │   (기억)    │  │   (환경)    │  │   (관측)    │          │  │
│  │   └─────────────┘  └─────────────┘  └─────────────┘          │  │
│  └───────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
3-Tier 아키텍처 요약
Tier	핵심 질문	포함 패턴
Design-Time	어떻게 생각하고 실행할 것인가?	Thinking, Execution, Coordination
Runtime	어떻게 신뢰성 있게 운영할 것인가?	State, Control, Saga
Infrastructure	무엇을 기억하고, 어디서 실행할 것인가?	Memory, Runtime Selection, Observability
Part 1: Design-Time Patterns (설계 시점 패턴)
“무엇을 생각하고, 어떻게 실행하고, 누가 협업할 것인가?”

1️⃣ Thinking Layer (인지 레이어)
핵심 개념
에이전트의 추론과 의사결정을 담당하는 레이어.

┌─────────────────────────────────────────────────────────┐
│                   Thinking Layer                        │
│                                                         │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐            │
│   │ 생성    │───▶│ 평가    │───▶│ 개선    │            │
│   └─────────┘    └─────────┘    └─────────┘            │
│        ▲                              │                 │
│        └──────── 반복 (Loop) ─────────┘                │
└─────────────────────────────────────────────────────────┘
1.1 Reflection (반성)
개념
에이전트가 자신의 출력물을 스스로 평가하고 개선하는 기본 사고 패턴.

구조
┌─────────┐     ┌─────────┐     ┌─────────┐
│  생성   │ ──▶ │  비평   │ ──▶ │  개선   │
│ (Draft) │     │(Critique)│    │(Refine) │
└─────────┘     └─────────┘     └─────────┘
예시 흐름
[생성] 재귀 피보나치 함수 (O(2^n))
[비평] "시간 복잡도 높음, 메모이제이션 필요"
[개선] 동적 프로그래밍 버전 (O(n))
사용처
코드 생성 및 리팩토링
문서/보고서 품질 개선
1.2 Self-Improvement Loop (자기 개선 루프)
개념
Reflection을 품질 임계값에 도달할 때까지 반복하는 확장 패턴.

핵심 코드 패턴
while revision_count < MAX_REVISIONS:
    critique = evaluate(draft)
    if critique.score >= QUALITY_THRESHOLD:
        break
    draft = revise(draft, critique.feedback)
    revision_count += 1
사용처
마케팅 카피라이팅
고품질 콘텐츠 생성
1.3 Reflexive Metacognitive (성찰적 메타인지)
개념
에이전트가 자신의 능력과 한계를 인식하고 적절한 전략을 선택하는 패턴.

전략 선택 로직
if analysis.is_emergency:
    return Strategy.ESCALATE
elif analysis.confidence < 0.5:
    return Strategy.ESCALATE
elif analysis.requires_tool:
    return Strategy.USE_TOOL
else:
    return Strategy.REASON_DIRECTLY
사용처
의료/법률/금융 등 고위험 도메인
책임 있는 AI 시스템
1.4 ReAct (Reason + Act)
개념
추론과 행동을 교차 반복하는 패턴. Reflection + Tool Use + Loop의 교차점.

구조
┌──────────────────────────────────────────────────────┐
│                    ReAct Loop                        │
│   ┌─────────┐   ┌─────────┐   ┌─────────────┐       │
│   │ Thought │──▶│ Action  │──▶│ Observation │       │
│   └─────────┘   └─────────┘   └──────┬──────┘       │
│        ▲                             │               │
│        └─────────────────────────────┘               │
└──────────────────────────────────────────────────────┘
예시
[Thought] "Dune 제작사를 찾아야 해"
[Action]  web_search("Dune production company")
[Observation] "Legendary Entertainment"
[Thought] "CEO를 찾아야 해"
[Action]  web_search("Legendary Entertainment CEO")
[Observation] "Joshua Grode"
[Final] "CEO는 Joshua Grode입니다"
1.5 Tree-of-Thoughts (ToT)
개념
여러 추론 경로를 동시에 탐색하고 최적 경로를 선택하는 패턴.

구조
                    [문제]
         ┌────────────┼────────────┐
      [경로 A]     [경로 B]     [경로 C]
      [평가: 3]    [평가: 7]    [평가: 2]
         X         계속 탐색        X
사용처
복잡한 퍼즐/최적화 문제
수학적 증명
Thinking Layer 비교표
패턴	핵심 메커니즘	반복	자기 인식	탐색
Reflection	자기 비평	1회	❌	❌
Self-Improvement	반복 개선	다회	❌	❌
Metacognitive	한계 인식	1회	✅	❌
ReAct	추론-행동 루프	다회	❌	❌
ToT	다중 경로 탐색	다회	❌	✅
2️⃣ Execution Layer (실행 레이어)
핵심 개념
계획 수립, 도구 사용, 실행 제어를 담당하는 레이어.

2.1 Planning (기본 계획)
구조
┌─────────┐     ┌─────────────────────────┐     ┌─────────┐
│  목표   │ ──▶ │  [1] → [2] → [3] → [4]  │ ──▶ │ 순차    │
│         │     │      계획 수립          │     │ 실행    │
└─────────┘     └─────────────────────────┘     └─────────┘
2.2 PEV (Planner-Executor-Verifier)
개념
Planning에 검증 단계를 추가하여 오류 시 재계획.

계획 → 실행 → 검증 → (실패 시) 재계획 → ...
2.3 ReWOO (계획-실행 분리)
개념
계획과 실행을 완전히 분리하여 토큰 효율성 향상.

ReAct:  Think → Act → Observe → Think → Act → ...
ReWOO:  Plan[1,2,3,4] → Execute[1,2,3,4] → Synthesize
2.4 Tool Use (도구 사용)
개념
LLM이 외부 도구를 호출하여 자신의 한계를 극복.

tools = [
    {"name": "web_search", "description": "Search the web"},
    {"name": "calculator", "description": "Math calculations"},
]
Execution Layer 비교표
패턴	검증	재계획	시뮬레이션	인간 승인
Planning	❌	❌	❌	❌
PEV	✅	✅	❌	❌
ReWOO	❌	❌	❌	❌
Tool Use	❌	❌	❌	❌
3️⃣ Coordination Layer (조정 레이어)
핵심 개념
여러 에이전트 간의 협업과 작업 분배를 담당.

3.1 Multi-Agent (기본 다중 에이전트)
        ┌─────────────┐
        │ Orchestrator│
        └──────┬──────┘
    ┌──────────┼──────────┐
    ▼          ▼          ▼
[Agent A] [Agent B] [Agent C]
    └──────────┼──────────┘
               ▼
        [Synthesizer]
3.2 Meta-Controller (라우터)
intent = classify(user_input)
if intent == "coding":
    return coder_agent(user_input)
elif intent == "research":
    return researcher_agent(user_input)
3.3 Blackboard (칠판)
공유 메모리에 정보 기록, 동적으로 다음 에이전트 선택.

[칠판] sentiment = "positive"
[Controller] "긍정 → 기술분석가 호출 (재무분석가 스킵)"
3.4 Ensemble (앙상블)
병렬 처리 → 결과 집계/투표.

[낙관론자] "강력 매수"
[비관론자] "보류"
[Aggregator] → "신중한 매수"
Coordination Layer 비교표
패턴	중앙 제어	동적 라우팅	공유 상태	병렬	투표
Multi-Agent	✅	❌	❌	가능	❌
Meta-Controller	✅	✅	❌	❌	❌
Blackboard	✅	✅	✅	❌	❌
Ensemble	❌	❌	❌	✅	✅
Part 2: Runtime Patterns (운영 시점 패턴)
“신뢰성은 모델 속성이 아니다. 엔지니어링 문제다.”

Design-Time 패턴이 "무엇을 할 것인가"를 다룬다면, Runtime 패턴은 **“실패했을 때 어떻게 복구할 것인가”**를 다룹니다.

🕐 Runtime 선택 가이드
패턴을 선택하기 전에, 문제가 어떤 Runtime에 속하는지 먼저 파악해야 합니다.

┌─────────────────────────────────────────────────────────────────────┐
│                       Runtime Selection                             │
├───────────────┬─────────────┬───────────────────────────────────────┤
│    Runtime    │  시간 범위  │            요구사항                    │
├───────────────┼─────────────┼───────────────────────────────────────┤
│Conversational │   초 단위   │ 서브초 응답, 모든 게이트가 레이턴시    │
│               │             │ 즉각적 피드백, 상태 최소화             │
├───────────────┼─────────────┼───────────────────────────────────────┤
│  Autonomous   │   분 단위   │ 병렬 실행, 일부 실패 허용              │
│               │             │ 부작용 Undo 필요, 보상 트랜잭션        │
├───────────────┼─────────────┼───────────────────────────────────────┤
│ Long-Horizon  │   일 단위   │ 지속성, 재개 가능성, 감사 추적         │
│               │             │ 재시작 내성, 체크포인팅                │
└───────────────┴─────────────┴───────────────────────────────────────┘
Runtime별 압력 포인트
Runtime	Coordination 압력	State 압력	Control 압력
Conversational	낮음	낮음	높음
Autonomous	높음	중간	중간
Long-Horizon	중간	높음	중간
4️⃣ State Dimension (상태 차원)
핵심 개념
실행 상태를 어떻게 관리하고, 실패 후 어떻게 복구할 것인가?

⚠️ Memory vs State: Memory는 “장기 기억”(지식), State는 “실행 상태”(워크플로우 진행 상황)

Memory: "사용자 Alex는 보수적 투자자다" (지식)
State:  "현재 3단계 중 2단계 완료, 다음은 offer_generation" (진행 상황)
4.1 Event-Driven Sequencing (이벤트 기반 시퀀싱)
개념
이벤트 로그가 진실의 원천(Source of Truth). 현재 상태는 이벤트를 재생하여 도출.

구조
┌─────────────────────────────────────────────────────────────────┐
│                    Event Log (불변, append-only)                │
├─────────────────────────────────────────────────────────────────┤
│ [T1] CustomerCreated {id: "C001", name: "Alex"}                │
│ [T2] ChurnScoreCalculated {id: "C001", score: 0.72}            │
│ [T3] OfferGenerated {id: "C001", discount: 20%}                │
│ [T4] OfferAccepted {id: "C001"}                                │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│              Current State (이벤트 재생으로 도출)                │
│  {id: "C001", status: "retained", discount_applied: 20%}       │
└─────────────────────────────────────────────────────────────────┘
핵심 특징
# 이벤트는 불변 (수정 불가, 추가만 가능)
event_log.append(Event("OfferGenerated", {"discount": 20}))

# 현재 상태는 이벤트 재생으로 계산
def get_current_state(customer_id):
    events = event_log.filter(customer_id)
    state = {}
    for event in events:
        state = apply_event(state, event)
    return state

# 시간 여행 가능 (특정 시점 상태 복원)
def get_state_at(customer_id, timestamp):
    events = event_log.filter(customer_id, before=timestamp)
    return replay(events)
장점
완벽한 감사 추적: 모든 변경 기록
시간 여행 디버깅: 과거 상태 복원 가능
재생 가능: 버그 수정 후 이벤트 재생으로 상태 재계산
분기 가능: “만약 이 결정이 달랐다면?” 시뮬레이션
사용처
금융 거래 기록
규제 준수가 필요한 시스템
복잡한 디버깅이 필요한 장기 워크플로우
4.2 Shared State Machine (공유 상태 머신)
개념
상태 전이 규칙을 명시적으로 정의하고, 잘못된 전이를 방지. 재시작 내성 확보.

구조
┌─────────────────────────────────────────────────────────────────┐
│                    State Machine Definition                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────┐    ┌─────────┐    ┌─────────┐    ┌─────────┐    │
│   │ pending │───▶│ scoring │───▶│offer_sent│───▶│ closed  │    │
│   └─────────┘    └────┬────┘    └────┬────┘    └─────────┘    │
│                       │              │                         │
│                       ▼              ▼                         │
│                 ┌──────────┐   ┌──────────┐                   │
│                 │  human   │   │ expired  │                   │
│                 │ required │   │          │                   │
│                 └──────────┘   └──────────┘                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
상태 전이 규칙
ALLOWED_TRANSITIONS = {
    "pending":        {"scoring"},
    "scoring":        {"offer_sent", "human_required"},
    "offer_sent":     {"closed", "human_required", "expired"},
    "human_required": {"offer_sent", "closed", "expired"},
    "closed":         set(),  # terminal state
    "expired":        set(),  # terminal state
}

def transition(current_state, next_state):
    if next_state not in ALLOWED_TRANSITIONS[current_state]:
        raise InvalidTransitionError(
            f"Cannot transition from {current_state} to {next_state}"
        )
    
    # 상태 변경 + 체크포인트 저장
    save_checkpoint(next_state)
    return next_state
재시작 내성
def resume_workflow(workflow_id):
    # 마지막 체크포인트에서 복원
    checkpoint = load_checkpoint(workflow_id)
    current_state = checkpoint.state
    
    # 해당 상태부터 계속 실행
    return continue_from(current_state)
장점
잘못된 전이 방지: 명시적 규칙으로 버그 예방
재시작 내성: 체크포인트에서 복구
시각화 용이: 상태 다이어그램으로 워크플로우 문서화
테스트 용이: 각 전이를 독립적으로 테스트 가능
사용처
장기 실행 워크플로우 (계약 갱신, 온보딩)
여러 날에 걸친 프로세스
명시적 승인이 필요한 워크플로우
State Dimension 비교표
패턴	진실의 원천	재생 가능	시간 여행	전이 검증	재시작 내성
Event-Driven	이벤트 로그	✅	✅	❌	✅
State Machine	현재 상태	❌	❌	✅	✅
5️⃣ Control Dimension (제어 차원)
핵심 개념
누가 실행을 제어하고, 정책을 강제하고, 언제 멈출지 결정하는가?

5.1 Supervisor + Gate (감독자 + 게이트)
개념
감독자가 에이전트를 모니터링하고, 게이트가 정책을 강제. 실패한 에이전트 재시작, 정책 위반 거부.

구조
┌─────────────────────────────────────────────────────────────────┐
│                         Supervisor                              │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ • 에이전트 상태 모니터링                                │   │
│  │ • 죽은 에이전트 재시작                                  │   │
│  │ • 전체 시스템 건강 상태 추적                            │   │
│  └─────────────────────────────────────────────────────────┘   │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              ┌─────────┐ ┌─────────┐ ┌─────────┐
              │ Agent 1 │ │ Agent 2 │ │ Agent 3 │
              └────┬────┘ └────┬────┘ └────┬────┘
                   │           │           │
                   └───────────┼───────────┘
                               ▼
                    ┌─────────────────────┐
                    │        Gate         │
                    │  ┌───────────────┐  │
                    │  │ Policy Check  │  │
                    │  │ • Rate Limit  │  │
                    │  │ • Budget Cap  │  │
                    │  │ • Content     │  │
                    │  │   Filter      │  │
                    │  └───────────────┘  │
                    └──────────┬──────────┘
                               │
                        ┌──────┴──────┐
                        │ Allow/Deny  │
                        └─────────────┘
Supervisor 구현
class Supervisor:
    def __init__(self, agents):
        self.agents = agents
        self.health_status = {}
    
    def monitor(self):
        for agent in self.agents:
            try:
                status = agent.health_check()
                self.health_status[agent.id] = status
            except AgentDeadError:
                self.restart(agent)
    
    def restart(self, agent):
        logger.warning(f"Restarting dead agent: {agent.id}")
        last_checkpoint = load_checkpoint(agent.id)
        new_agent = Agent.from_checkpoint(last_checkpoint)
        self.agents.replace(agent, new_agent)
Gate 구현
class PolicyGate:
    def __init__(self):
        self.rate_limiter = RateLimiter(max_calls=100, per_minute=1)
        self.budget_tracker = BudgetTracker(daily_limit=10.0)  # $10/day
        self.content_filter = ContentFilter()
    
    def check(self, action) -> GateDecision:
        # Rate Limit Check
        if not self.rate_limiter.allow():
            return GateDecision.DENY, "Rate limit exceeded"
        
        # Budget Check
        estimated_cost = estimate_cost(action)
        if not self.budget_tracker.can_spend(estimated_cost):
            return GateDecision.DENY, "Budget exhausted"
        
        # Content Policy Check
        if not self.content_filter.is_safe(action):
            return GateDecision.DENY, "Policy violation"
        
        return GateDecision.ALLOW, None
사용처
프로덕션 에이전트 시스템
비용 관리가 필요한 시스템
정책 준수가 중요한 환경
5.2 Human-in-the-Loop (인간 참여)
개념
4가지 제어 평면을 통해 인간이 에이전트 실행을 제어.

4가지 제어 평면
┌─────────────────────────────────────────────────────────────────┐
│                  Human Control Planes                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   1. KILL SWITCH (비상 정지)                                   │
│      ├── 즉시 모든 실행 중단                                   │
│      └── 복구 불가, 클린업 시작                                │
│                                                                 │
│   2. ESCALATION (에스컬레이션)                                 │
│      ├── 에이전트가 확신 없을 때 인간에게 위임                 │
│      └── "이 결정은 제가 내리기 어렵습니다"                    │
│                                                                 │
│   3. APPROVAL (승인)                                           │
│      ├── 중요한 액션 전 인간 승인 대기                         │
│      └── Dry-Run → Preview → Approve/Reject                   │
│                                                                 │
│   4. THROTTLING (제한)                                         │
│      ├── 속도 제한, 예산 제한                                  │
│      └── 점진적 제동, 완전 정지 아님                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
구현 예시
class HumanInTheLoop:
    def __init__(self):
        self.kill_switch = KillSwitch()
        self.approval_queue = ApprovalQueue()
        self.throttle = Throttle(rate_limit=10, budget_limit=50.0)
    
    # 1. Kill Switch
    def emergency_stop(self):
        self.kill_switch.activate()
        # 모든 에이전트에 중단 신호 전송
        broadcast(Signal.TERMINATE)
    
    # 2. Escalation
    def escalate(self, agent, reason):
        agent.suspend()
        ticket = create_support_ticket(
            agent_id=agent.id,
            reason=reason,
            context=agent.get_context()
        )
        return wait_for_human_response(ticket)
    
    # 3. Approval
    def request_approval(self, action, timeout=300):
        preview = action.dry_run()
        self.approval_queue.add(action, preview)
        
        decision = wait_for_decision(timeout)
        if decision == "approve":
            return action.execute()
        else:
            return ActionRejected(decision.reason)
    
    # 4. Throttling
    def throttled_execute(self, action):
        if not self.throttle.allow():
            return ThrottledResponse("Rate/budget limit reached")
        return action.execute()
Approval Flow (Dry-Run 포함)
┌─────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────┐
│ Action  │ ──▶ │  Dry-Run    │ ──▶ │   Human     │ ──▶ │ Execute │
│ Proposed│     │  (Preview)  │     │  Decision   │     │  or     │
└─────────┘     └──────┬──────┘     └──────┬──────┘     │ Reject  │
                       │                   │            └─────────┘
                       ▼                   │
                ┌─────────────┐            │
                │ "이메일 발송│            │
                │  예정:      │◀───────────┘
                │  To: ...    │       (Approve/Reject)
                │  Subject:..."│
                └─────────────┘
사용처
민감한 작업 (이메일 발송, 결제, 계약)
되돌릴 수 없는 액션
규제 준수 필요 환경
Control Dimension 비교표
패턴	자동 복구	정책 강제	인간 개입	비상 정지
Supervisor	✅	❌	❌	❌
Gate	❌	✅	❌	❌
Supervisor + Gate	✅	✅	❌	❌
Human-in-the-Loop	❌	❌	✅	✅
Full Control Stack	✅	✅	✅	✅
6️⃣ Saga Dimension (보상 트랜잭션)
핵심 개념
분산 트랜잭션에서 일부 실패 시 보상 액션으로 롤백. 전통적 DB 트랜잭션(ACID)을 분산 시스템에 적용.

6.1 Scatter-Gather + Saga
개념
병렬 실행(Scatter-Gather) + 실패 시 보상(Saga) 조합.

구조
┌─────────────────────────────────────────────────────────────────┐
│                    Scatter-Gather + Saga                        │
│                                                                 │
│   Phase 1: Scatter (병렬 실행)                                 │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │              Orchestrator                               │  │
│   │                   │                                      │  │
│   │      ┌────────────┼────────────┐                        │  │
│   │      ▼            ▼            ▼                        │  │
│   │  [호텔 예약]  [항공 예약]  [렌터카 예약]                │  │
│   │      │            │            │                        │  │
│   │      ✓            ✓            ✗ (실패)                │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                 │
│   Phase 2: Saga (보상 트랜잭션)                                │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │                                                         │  │
│   │  [호텔 취소] ◀── [항공 취소] ◀── (렌터카는 이미 실패)  │  │
│   │      │            │                                     │  │
│   │      ✓            ✓                                     │  │
│   │                                                         │  │
│   │  → 모든 것이 원래 상태로 복구됨                        │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
구현
class SagaOrchestrator:
    def __init__(self):
        self.completed_actions = []
    
    def execute_with_saga(self, actions):
        try:
            # Phase 1: Scatter (병렬 실행)
            results = parallel_execute(actions)
            
            for action, result in zip(actions, results):
                if result.success:
                    self.completed_actions.append(action)
                else:
                    # 하나라도 실패하면 Saga 시작
                    raise ActionFailedError(action, result.error)
            
            return SuccessResult(results)
        
        except ActionFailedError as e:
            # Phase 2: Saga (역순으로 보상)
            self.compensate()
            return FailureResult(e, compensated=True)
    
    def compensate(self):
        # 완료된 액션들을 역순으로 보상
        for action in reversed(self.completed_actions):
            compensation = action.get_compensation()
            compensation.execute()
            logger.info(f"Compensated: {action}")
보상 액션 정의
class BookHotelAction:
    def execute(self):
        self.booking_id = hotel_api.book(...)
        return self.booking_id
    
    def get_compensation(self):
        return CancelHotelAction(self.booking_id)

class CancelHotelAction:
    def __init__(self, booking_id):
        self.booking_id = booking_id
    
    def execute(self):
        hotel_api.cancel(self.booking_id)
사용처
여행 예약 시스템 (호텔 + 항공 + 렌터카)
주문 처리 (재고 확인 + 결제 + 배송)
멀티 서비스 오케스트레이션
Saga 패턴 비교표
시나리오	Saga 필요?	보상 액션 예시
호텔 예약 성공 → 항공 실패	✅	호텔 취소
재고 확보 → 결제 실패	✅	재고 반환
이메일 발송 (되돌릴 수 없음)	❌	불가능
DB 쓰기 (트랜잭션)	❌	ROLLBACK
Part 3: Infrastructure (인프라)
“어디에 저장하고, 어디서 실행하고, 어떻게 관측할 것인가?”

7️⃣ Memory Layer (기억 레이어)
핵심 개념
에이전트에게 장기 기억을 부여. 대화 간 정보 유지, 개인화.

⚠️ State vs Memory

State: 현재 워크플로우 진행 상황 (Runtime)
Memory: 축적된 지식과 경험 (Infrastructure)
7.1 Episodic Memory (에피소드 기억)
항목	설명
저장 내용	과거 대화 요약, 상호작용 기록
저장소	Vector DB (ChromaDB, Pinecone)
검색	의미적 유사도 검색
질문	“무슨 일이 있었나?”
# 저장
memory.add("사용자 Alex는 보수적 투자자이며 기술주에 관심")

# 검색
results = memory.search("Alex의 투자 성향", k=3)
7.2 Semantic Memory (의미 기억)
항목	설명
저장 내용	추출된 사실, 사용자 프로필
저장소	Key-Value Store, Structured DB
검색	정확 매칭, Key Lookup
질문	“무엇을 아는가?”
{
  "user_profile": {
    "name": "Alex",
    "investment_style": "conservative",
    "risk_tolerance": "low"
  }
}
7.3 Graph Memory (그래프 기억)
항목	설명
저장 내용	엔티티 간 관계
저장소	Graph DB (Neo4j)
검색	Cypher Query, Graph Traversal
질문	“어떻게 연결되어 있는가?”
// "BetaSolutions를 인수한 회사의 직원은?"
MATCH (p:Person)-[:WORKS_FOR]->(c:Company)-[:ACQUIRED]->(:Company {name:'BetaSolutions'})
RETURN p.name
Memory Layer 비교표
유형	저장 내용	저장소	검색 방식	강점
Episodic	대화/이벤트	Vector DB	유사도	맥락 회상
Semantic	사실/프로필	KV Store	정확 매칭	빠른 조회
Graph	관계/연결	Graph DB	탐색	다중 홉 추론
8️⃣ Runtime Selection (런타임 선택)
프레임워크 선택 가이드
프레임워크	강점	적합한 Runtime
LangGraph	상태 그래프, 체크포인팅	Long-Horizon
Google ADK	Human-in-the-Loop	Conversational, Autonomous
Temporal	워크플로우 내구성	Long-Horizon
CrewAI	멀티 에이전트 협업	Autonomous
AutoGen	대화형 멀티 에이전트	Conversational
Runtime별 추천 스택
┌─────────────────────────────────────────────────────────────────┐
│                   Runtime → Stack Mapping                       │
├───────────────┬─────────────────────────────────────────────────┤
│Conversational │ LangGraph + Redis (세션)                        │
│               │ 최소 상태, 빠른 응답                             │
├───────────────┼─────────────────────────────────────────────────┤
│  Autonomous   │ LangGraph + Saga + Gate                         │
│               │ 병렬 실행, 보상 트랜잭션, 정책 강제             │
├───────────────┼─────────────────────────────────────────────────┤
│ Long-Horizon  │ LangGraph + PostgreSQL + Event Sourcing         │
│               │ 체크포인팅, 감사 추적, 재개 가능                │
└───────────────┴─────────────────────────────────────────────────┘
9️⃣ Observability (관측성)
핵심 개념
에이전트 시스템의 내부 상태를 외부에서 관측. 디버깅, 모니터링, 감사.

3가지 관측 축
┌─────────────────────────────────────────────────────────────────┐
│                    Observability Pillars                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   1. LOGS (로그)                                               │
│      ├── 이벤트 기록                                           │
│      ├── 에러 추적                                             │
│      └── 구조화된 로깅 (JSON)                                  │
│                                                                 │
│   2. METRICS (메트릭)                                          │
│      ├── 레이턴시, 처리량                                      │
│      ├── 성공/실패율                                           │
│      ├── 토큰 사용량, 비용                                     │
│      └── 에이전트별 성능                                       │
│                                                                 │
│   3. TRACES (트레이스)                                         │
│      ├── 요청의 전체 경로 추적                                 │
│      ├── 에이전트 간 호출 관계                                 │
│      └── 도구 호출 타임라인                                    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
LangSmith 통합 예시
import os
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGCHAIN_PROJECT"] = "my-agent-project"

# 자동으로 모든 LangGraph 실행이 추적됨
result = app.invoke({"query": "..."})

# LangSmith 대시보드에서 확인:
# - 각 노드별 실행 시간
# - 입력/출력 데이터
# - 토큰 사용량
# - 에러 스택트레이스
커스텀 메트릭 예시
from prometheus_client import Counter, Histogram

# 메트릭 정의
agent_calls = Counter('agent_calls_total', 'Total agent calls', ['agent', 'status'])
agent_latency = Histogram('agent_latency_seconds', 'Agent latency', ['agent'])

# 사용
with agent_latency.labels(agent='researcher').time():
    result = researcher_agent.invoke(query)
    
agent_calls.labels(agent='researcher', status='success').inc()
🔧 통합 패턴 선택 가이드
Decision Tree
                        [문제 정의]
                            │
              ┌─────────────┴─────────────┐
              ▼                           ▼
        [시간 범위?]                 [실패 시?]
              │                           │
    ┌─────────┼─────────┐       ┌─────────┼─────────┐
    ▼         ▼         ▼       ▼         ▼         ▼
  초 단위   분 단위   일 단위  무시 가능  복구 필요  되돌려야 함
    │         │         │       │         │         │
    ▼         ▼         ▼       ▼         ▼         ▼
Conver-   Autono-    Long-    Basic    PEV +     Saga
sational    mous    Horizon  Planning  State
상황별 추천 조합
상황	Design-Time	Runtime	Infrastructure
챗봇	ReAct + Tool Use	-	Episodic Memory
코드 생성	Reflection + ToT	-	-
고객 지원	Meta-Controller + Multi-Agent	Supervisor + Gate	Semantic Memory
예약 시스템	Planning	Saga + Human Approval	Event Sourcing
계약 갱신 (90일)	Multi-Agent	State Machine + Saga + Human	Full Stack
투자 분석	Ensemble + Metacognitive	Simulator + Gate	Graph Memory
복잡도별 아키텍처
🟢 Level 1: 단순 (POC)
ReAct + Tool Use
🟡 Level 2: 중간 (MVP)
Meta-Controller
       │
       ├──▶ Agent A (ReAct)
       ├──▶ Agent B (ReAct)
       └──▶ Agent C (ReAct)
       
+ Episodic Memory
+ Basic Logging
🔴 Level 3: 프로덕션
┌─────────────────────────────────────────┐
│            User Request                 │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  Metacognitive (범위/위험 확인)         │  ← Thinking
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  Meta-Controller (라우팅)               │  ← Coordination
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  Blackboard + Multi-Agent               │  ← Coordination
│  (동적 전문가 협업)                     │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  Supervisor + Gate                      │  ← Control
│  (모니터링 + 정책 강제)                 │
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  Saga (보상 트랜잭션)                   │  ← Saga
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  Human-in-the-Loop (승인)               │  ← Control
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  Event Sourcing + Checkpoint            │  ← State
└──────────────────┬──────────────────────┘
                   ▼
┌─────────────────────────────────────────┐
│  Memory + Observability                 │  ← Infrastructure
└─────────────────────────────────────────┘
📝 핵심 요약
3-Tier 아키텍처
Tier	핵심 질문	패턴들
Design-Time	어떻게 생각하고 실행할 것인가?	Reflection, ReAct, ToT, Planning, PEV, Multi-Agent, Ensemble
Runtime	어떻게 신뢰성 있게 운영할 것인가?	Event Sourcing, State Machine, Supervisor, Gate, Human-in-the-Loop, Saga
Infrastructure	무엇을 기억하고 관측할 것인가?	Episodic/Semantic/Graph Memory, Observability
핵심 원칙
Runtime부터 시작: 패턴이 아니라 문제의 시간 범위부터 파악
State는 척추: 상태 관리가 모든 것의 기반
Control이 경계: 정책과 인간 개입이 시스템을 안전하게 유지
신뢰성은 엔지니어링: 모델 성능이 아니라 시스템 설계의 문제
“좋은 에이전트는 모델보다 워크플로우 설계가 먼저다.” “Operations console을 에이전트보다 먼저 만들어라.”

📚 참고 자료
Papers
ReAct - Yao et al.
Tree of Thoughts - Yao et al.
Reflexion - Shinn et al.
ReWOO - Xu et al.
τ-bench - Yao et al.
Frameworks
LangGraph
Google ADK
LangSmith
Repository
agent-runtime-patterns - Vasundra Srinivasan
