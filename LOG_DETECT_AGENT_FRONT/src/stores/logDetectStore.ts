import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { agentApi } from '@/api/agentApi'
import { connectExecutionStream } from '@/services/streamingService'
import { useObservabilityStore } from '@/stores/observabilityStore'
import type {
  AgentReasoningEvent,
  AgentStepStatus,
  AnalyzeRequest,
  Cluster,
  DuplicatePatternCandidate,
  ExceptionRegistryItem,
  ExecutionStatus,
  FingerprintManualMergeResponse,
  KnowledgeCardItem,
  PatternClusterPartialRefreshResponse,
  PatternOpsSkill,
  PatternOpsSkillEdge,
  PatternOpsSkillExecution,
  PatternOpsValidatorResult,
  SkillActivityStreamItem,
  RecommendationHistoryItem,
  SharedState
} from '@/types/agentTypes'

const stepNames = [
  '분석 범위 확인',
  '로그 수집/정규화',
  '템플릿 추출/Fingerprint',
  '임베딩/유사 FP 검색',
  'FP 군집/병합 후보',
  'Time-window/상태 벡터',
  '추천/결과 정리'
]

const analysisStepNames = stepNames.filter((name) => name !== '추천/결과 정리')

const stepLogMessages: Record<string, string> = {
  '분석 범위 확인':
    '요청 범위, 대상 서비스, 분석 기준일, 이전 실행 상태를 확인하고 있습니다.',
  '로그 수집/정규화':
    '선택한 서비스의 원천 로그를 가져오고 분석 가능한 이벤트 형태로 정규화하고 있습니다.',
  '템플릿 추출/Fingerprint':
    '로그 메시지를 템플릿으로 추출하고 fingerprint 단위로 묶고 있습니다.',
  '임베딩/유사 FP 검색':
    'fingerprint 임베딩과 유사도 기준으로 기존 패턴 및 유사 fingerprint를 찾고 있습니다.',
  'FP 군집/병합 후보':
    '유사 fingerprint 군집과 병합 후보를 평가하고 승인 대기 항목을 정리하고 있습니다.',
  'Time-window/상태 벡터':
    '시간 창별 이벤트를 집계하고 trajectory modeling에 사용할 시스템 상태 벡터를 생성하고 있습니다.',
  '추천/결과 정리':
    '분석 근거를 종합해 영향 범위, 조치 방향, 재발 방지 권고안을 정리하고 있습니다.',
  Completed: '분석 skill 실행이 완료되었습니다.'
}

const agentStageToSkillStage: Record<string, string> = {
  'Starting execution': stepNames[0],
  OrchestratorAgent: stepNames[0],
  LogCollectorAgent: stepNames[1],
  LogAnalysisAgent: stepNames[2],
  KnowledgeBaseRAGAgent: stepNames[3],
  AnomalyDetectionAgent: stepNames[5],
  RecommendationAgent: stepNames[6],
  Completed: 'Completed'
}

interface KnowledgeCardApprovalDraft {
  cause: string
  recommendation: string
  resolutionMethod: string
  confidence: string
}

function buildDefaultRequest(
  serviceName: string,
  analysisDate?: string,
  streamId?: string
): AnalyzeRequest {
  return {
    service_name: serviceName,
    goal: `${serviceName} service log anomaly investigation`,
    save_to_chromadb: true,
    analysis_date: analysisDate || undefined,
    include_similar_clusters: false,
    include_time_windows: true,
    stream_id: streamId
  }
}

function createStreamId(): string {
  return `${Date.now()}-${Math.floor(Math.random() * 100000)}`
}

export const useLogDetectStore = defineStore('logDetect', () => {
  const executionStatus = ref<ExecutionStatus>('idle')
  const currentStage = ref<string>('Not started')
  const currentExecutionLog = ref<string>('')
  const lastExecutionAt = ref<string | null>(null)
  const healthModel = ref<string>('unknown')
  const healthStatus = ref<string>('unknown')
  const stubMode = ref<string>('unknown')
  const loading = ref(false)
  const loadingServices = ref(false)
  const loadingRecommendations = ref(false)
  const loadingKnowledgeCards = ref(false)
  const loadingExceptions = ref(false)
  const loadingDuplicatePatternCandidates = ref(false)
  const loadingPatternOpsSkills = ref(false)
  const recommendationGeneratingFingerprint = ref<string | null>(null)
  const backendActionCount = ref(0)
  const backendActionLabel = ref('')
  const selectedServiceName = ref('')
  const selectedAnalysisDate = ref(new Date().toISOString().slice(0, 10))
  const error = ref<string | null>(null)
  const serviceOptions = ref<string[]>([])
  const state = ref<SharedState | null>(null)
  // Trajectory Dashboard UI-only state. Kept separate from analysis results so
  // switching tabs never mutates or re-fetches /analyze evidence.
  const activeTrajectoryTab = ref<'modeling' | 'recfm'>('modeling')
  const selectedRecFMTrajectoryId = ref<string | null>(null)
  const selectedRecFMHorizon = ref<1 | 2 | 4>(1)
  const recommendationHistory = ref<RecommendationHistoryItem[]>([])
  const knowledgeCards = ref<KnowledgeCardItem[]>([])
  const exceptionRegistry = ref<ExceptionRegistryItem[]>([])
  const duplicatePatternCandidates = ref<DuplicatePatternCandidate[]>([])
  const patternOpsSkills = ref<PatternOpsSkill[]>([])
  const patternOpsSkillEdges = ref<PatternOpsSkillEdge[]>([])
  const skillActivityStream = ref<SkillActivityStreamItem[]>([])
  const toasts = ref<
    Array<{ id: number; level: 'info' | 'error'; message: string }>
  >([])
  const agentTimeline = ref<AgentStepStatus[]>(
    stepNames.map((name) => ({ name, status: 'pending' }))
  )
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let stageTimer: ReturnType<typeof setInterval> | null = null
  let localStageIndex = 0
  let localProgressStepNames = analysisStepNames
  let stream: EventSource | null = null
  let streamedSkillExecutionIds = new Set<string>()

  const scenarioSummary = computed(
    () => state.value?.final.evidence_bundle?.summary ?? state.value?.evidence.summary
  )
  const recommendationSummary = computed(
    () =>
      state.value?.final.evidence_bundle?.recommendation ??
      state.value?.evidence.recommendation
  )

  const riskClassification = computed(() => {
    const level = scenarioSummary.value?.risk_level
    if (level) return level
    const score = state.value?.assessment.risk_score ?? 0
    if (score >= 90) return 'Critical'
    if (score >= 70) return 'High'
    if (score >= 40) return 'Medium'
    return 'Low'
  })

  const overview = computed(() => ({
    totalLogs:
      scenarioSummary.value?.total_logs ??
      state.value?.evidence.normalized_logs.length ??
      0,
    totalFingerprints:
      scenarioSummary.value?.total_fingerprints ??
      state.value?.evidence.clusters.length ??
      0,
    knownPatterns: scenarioSummary.value?.known_patterns ?? 0,
    newPatterns: scenarioSummary.value?.new_patterns ?? 0,
    anomaliesDetected:
      scenarioSummary.value?.anomalies_detected ??
      state.value?.evidence.anomalies.length ??
      0,
    exceptionRegisteredCount:
      scenarioSummary.value?.exception_registered_count ?? 0,
    exceptionExcludedLogs:
      scenarioSummary.value?.exception_excluded_logs ?? 0,
    riskScore:
      scenarioSummary.value?.risk_score ??
      state.value?.assessment.risk_score ??
      0,
    riskLevel: scenarioSummary.value?.risk_level ?? riskClassification.value,
    detectionStatus: scenarioSummary.value?.detection_status ?? 'Not analyzed',
    impactScore:
      scenarioSummary.value?.risk_score ??
      state.value?.assessment.risk_score ??
      0
  }))

  const currentRecommendationFingerprint = computed(() => {
    const bundle = state.value?.final.evidence_bundle as
      | Record<string, unknown>
      | undefined
    const recommendation = bundle?.recommendation as
      | Record<string, unknown>
      | undefined

    if (typeof bundle?.selected_fingerprint === 'string') {
      return bundle.selected_fingerprint
    }
    if (typeof recommendation?.fingerprint === 'string') {
      return recommendation.fingerprint
    }
    return state.value?.evidence.clusters[0]?.cluster ?? null
  })

  const currentRecommendationCause = computed(() => {
    const bundle = state.value?.final.evidence_bundle as
      | Record<string, unknown>
      | undefined
    const recommendation = bundle?.recommendation as
      | Record<string, unknown>
      | undefined
    if (typeof recommendation?.cause === 'string') return recommendation.cause
    return state.value?.final.executive_summary ?? ''
  })

  const currentRecommendationConfidence = computed(() => {
    const bundle = state.value?.final.evidence_bundle as
      | Record<string, unknown>
      | undefined
    const recommendation = bundle?.recommendation as
      | Record<string, unknown>
      | undefined
    if (typeof recommendation?.confidence === 'string') {
      return recommendation.confidence
    }
    return state.value?.assessment.confidence?.toUpperCase() ?? 'MEDIUM'
  })

  const patternOpsSkillExecutions = computed<PatternOpsSkillExecution[]>(() => {
    const evidenceExecutions =
      state.value?.evidence.pattern_ops_skill_executions
    if (evidenceExecutions?.length) return evidenceExecutions
    return (
      (state.value?.final.evidence_bundle
        ?.pattern_ops_skill_executions as PatternOpsSkillExecution[] | undefined) ??
      []
    )
  })

  const patternOpsSkillPlan = computed(() => {
    return (
      state.value?.evidence.pattern_ops_skill_plan ??
      state.value?.final.evidence_bundle?.pattern_ops_skill_plan ??
      null
    )
  })

  const patternOpsValidatorResults = computed<PatternOpsValidatorResult[]>(() => {
    const evidenceResults = state.value?.evidence.pattern_ops_validator_results
    if (evidenceResults?.length) return evidenceResults
    return (
      (state.value?.final.evidence_bundle
        ?.pattern_ops_validator_results as
        | PatternOpsValidatorResult[]
        | undefined) ?? []
    )
  })

  const currentSkillActivity = computed<SkillActivityStreamItem | null>(() => {
    return skillActivityStream.value[0] ?? null
  })

  const skillOpsOverview = computed(() => {
    const executions = patternOpsSkillExecutions.value
    const selected = new Set(executions.map((item) => item.skill_id))
    const success = executions.filter((item) => item.status === 'success').length
    const failed = executions.filter((item) => item.status === 'failed').length
    const selectedOnly = executions.filter(
      (item) => item.status === 'selected' || item.status === 'planned'
    ).length
    return {
      selected: selected.size,
      success,
      failed,
      selectedOnly
    }
  })

  const backendActionPending = computed(() => backendActionCount.value > 0)

  async function withBackendAction<T>(
    label: string,
    action: () => Promise<T>
  ): Promise<T> {
    backendActionCount.value += 1
    backendActionLabel.value = label
    try {
      return await action()
    } finally {
      backendActionCount.value = Math.max(0, backendActionCount.value - 1)
      if (backendActionCount.value === 0) {
        backendActionLabel.value = ''
      }
    }
  }

  function addToast(level: 'info' | 'error', message: string) {
    const id = Date.now() + Math.floor(Math.random() * 1000)
    toasts.value.push({ id, level, message })
    setTimeout(() => {
      toasts.value = toasts.value.filter((item) => item.id !== id)
    }, 3500)
  }

  function errorMessage(caught: unknown): string {
    const error = caught as {
      message?: string
      response?: { data?: { detail?: string } }
    }
    return error.response?.data?.detail || error.message || 'Unknown error'
  }

  function applyPatternClusterPartialRefresh(
    refresh?: PatternClusterPartialRefreshResponse
  ) {
    if (!state.value || !refresh) return
    const updatedClusters = refresh.updated_clusters
    const updatedByCluster = new Map<string, Cluster>(
      updatedClusters.map((cluster) => [cluster.cluster, cluster])
    )
    const removed = new Set(refresh.missing_fingerprints)
    refresh.affected_fingerprints.forEach((fingerprint) => {
      if (!updatedByCluster.has(fingerprint)) removed.add(fingerprint)
    })
    const nextClusters = state.value.evidence.clusters.filter((cluster) => {
      if (removed.has(cluster.cluster)) return false
      const updated = updatedByCluster.get(cluster.cluster)
      if (!updated) return true
      Object.assign(cluster, updated)
      updatedByCluster.delete(cluster.cluster)
      return true
    })
    nextClusters.push(...updatedByCluster.values())
    nextClusters.sort((left, right) => right.count - left.count)
    state.value.evidence.clusters = nextClusters
    refreshScenarioSummaryFromClusters()
  }

  function refreshScenarioSummaryFromClusters() {
    if (!state.value) return
    const clusters = state.value.evidence.clusters
    const knownCount = clusters.filter((cluster) =>
      ['known_exact', 'known_similar'].includes(cluster.pattern_status ?? '')
    ).length
    const newCount = clusters.filter(
      (cluster) => cluster.pattern_status === 'new_pattern'
    ).length
    const summaries = [
      state.value.evidence.summary,
      state.value.final.evidence_bundle?.summary
    ].filter((summary) => summary !== undefined)
    summaries.forEach((summary) => {
      summary.total_fingerprints = clusters.length
      summary.known_patterns = knownCount
      summary.new_patterns = newCount
    })
  }

  function appendSkillActivity(
    activity: Omit<SkillActivityStreamItem, 'id' | 'at'>
  ) {
    if (activity.execution_id) {
      streamedSkillExecutionIds.add(activity.execution_id)
    }
    const id = `${Date.now()}-${Math.floor(Math.random() * 100000)}`
    const item = {
      ...activity,
      id,
      at: new Date().toISOString()
    }
    const [latest] = skillActivityStream.value
    if (
      latest &&
      latest.skill === item.skill &&
      latest.status === item.status &&
      latest.action === item.action &&
      latest.source === item.source
    ) {
      skillActivityStream.value = [
        { ...latest, at: item.at, detail: item.detail || latest.detail },
        ...skillActivityStream.value.slice(1)
      ]
      return
    }
    skillActivityStream.value = [item, ...skillActivityStream.value].slice(0, 80)
  }

  function resetSkillActivityStream(serviceName: string, action: string) {
    skillActivityStream.value = []
    streamedSkillExecutionIds = new Set<string>()
    appendSkillActivity({
      skill: '분석 요청 접수',
      agent: 'Dashboard',
      status: 'running',
      action,
      detail: `${serviceName} 서비스 분석 요청을 백엔드로 전달했습니다.`,
      source: 'user-action'
    })
  }

  function skillNameById(result: SharedState, skillId: string): string {
    const plans = [
      ...(result.evidence.pattern_ops_skill_plan?.selected_skills ?? []),
      ...(result.final.evidence_bundle?.pattern_ops_skill_plan?.selected_skills ?? [])
    ]
    const matched = plans.find((item) => item.skill_id === skillId)
    return matched?.name || skillId
  }

  function appendPatternOpsExecutionActivities(result: SharedState) {
    const executions =
      result.evidence.pattern_ops_skill_executions ??
      result.final.evidence_bundle?.pattern_ops_skill_executions ??
      []
    executions.slice(-12).forEach((execution) => {
      if (streamedSkillExecutionIds.has(execution.execution_id)) return
      appendSkillActivity({
        execution_id: execution.execution_id,
        skill: skillNameById(result, execution.skill_id),
        agent: execution.agent_name,
        status: execution.status,
        action: `${execution.scope} skill ${execution.status}`,
        detail: execution.reason || execution.skill_id,
        source: 'backend-result'
      })
    })
  }

  function appendStreamedSkillExecution(
    execution: PatternOpsSkillExecution & { skill_name?: string }
  ) {
    appendSkillActivity({
      execution_id: execution.execution_id,
      skill: execution.skill_name || execution.skill_id,
      agent: execution.agent_name,
      status: execution.status,
      action: `${execution.scope} skill ${execution.status}`,
      detail: execution.reason || execution.skill_id,
      source: 'sse'
    })
  }

  function appendReasoningActivity(
    event: AgentReasoningEvent,
    source: SkillActivityStreamItem['source']
  ) {
    if (streamedSkillExecutionIds.has(event.event_id)) return
    appendSkillActivity({
      execution_id: event.event_id,
      skill: event.title,
      agent: event.agent_name,
      status: event.status,
      action: event.detail,
      detail: reasoningMetadataSummary(event),
      reasoning_kind: event.kind,
      source
    })
  }

  function appendReasoningActivities(result: SharedState) {
    const events =
      result.evidence.agent_reasoning_events ??
      result.final.evidence_bundle?.agent_reasoning_events ??
      []
    events.forEach((event) => appendReasoningActivity(event, 'backend-result'))
  }

  function reasoningMetadataSummary(
    event: AgentReasoningEvent
  ): string | undefined {
    if (event.kind === 'planning') {
      const skills = event.metadata.selected_skill_ids
      if (Array.isArray(skills) && skills.length) {
        return `선택 스킬: ${skills.join(', ')}`
      }
    }
    if (
      event.kind === 'tool_call' &&
      typeof event.metadata.tool_name === 'string'
    ) {
      return `도구: ${event.metadata.tool_name}`
    }
    if (event.kind === 'self_correction') {
      const score = event.metadata.score
      const threshold = event.metadata.threshold
      if (typeof score === 'number' && typeof threshold === 'number') {
        return `품질 점수: ${score}/100 · 통과 기준: ${threshold}`
      }
    }
    return undefined
  }

  function markTimelineFromState(result: SharedState) {
    const run = new Set(result.decisions.agents_run)
    const skipped = new Set(result.decisions.skipped_agents)
    const failed = new Set(result.decisions.failures.map((f) => f.node))
    const failedSkills = new Set(
      result.decisions.failures
        .map((f) => agentStageToSkillStage[f.node])
        .filter(Boolean)
    )
    const skippedSkills = new Set(
      result.decisions.skipped_agents
        .map((agent) => agentStageToSkillStage[agent])
        .filter(Boolean)
    )
    const runSkills = new Set(
      result.decisions.agents_run
        .map((agent) => agentStageToSkillStage[agent])
        .filter(Boolean)
    )
    const completedWithoutFailure = run.size > 0 && failed.size === 0

    agentTimeline.value = stepNames.map((name) => {
      if (failedSkills.has(name)) return { name, status: 'failed' }
      if (skipped.has(name) || skippedSkills.has(name)) {
        return { name, status: 'skipped' }
      }
      if (completedWithoutFailure) return { name, status: 'completed' }
      if (runSkills.has(name)) return { name, status: 'completed' }
      return { name, status: 'pending' }
    })

    const current = agentTimeline.value.find((s) => s.status === 'pending')
    setCurrentStage(current ? current.name : 'Completed')
  }

  function closeStreamAndPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    if (stream) {
      stream.close()
      stream = null
    }
    if (stageTimer) {
      clearInterval(stageTimer)
      stageTimer = null
    }
  }

  function setCurrentStage(
    stage: string,
    source: SkillActivityStreamItem['source'] = 'local-stage'
  ) {
    const normalizedStage = agentStageToSkillStage[stage] ?? stage
    currentStage.value = normalizedStage
    currentExecutionLog.value =
      stepLogMessages[normalizedStage] ||
      `${normalizedStage}: 현재 단계를 실행하고 있습니다.`

    appendSkillActivity({
      skill: normalizedStage,
      agent: stage === normalizedStage ? undefined : stage,
      status: normalizedStage === 'Completed' ? 'completed' : 'running',
      action:
        normalizedStage === 'Completed'
          ? '분석 결과 정리 완료'
          : currentExecutionLog.value,
      detail:
        normalizedStage === 'Completed'
          ? '백엔드 분석 flow가 완료되었습니다.'
          : `Backend stage: ${stage}`,
      source
    })

    const activeIndex = stepNames.indexOf(normalizedStage)
    if (activeIndex < 0) return
    localStageIndex = activeIndex

    agentTimeline.value = stepNames.map((name, index) => {
      const previous = agentTimeline.value.find((step) => step.name === name)
      if (previous?.status === 'failed' || previous?.status === 'skipped') {
        return previous
      }
      if (index < activeIndex) return { name, status: 'completed' }
      if (index === activeIndex) return { name, status: 'running' }
      return { name, status: 'pending' }
    })
  }

  function startLocalStageProgress() {
    if (stageTimer) {
      clearInterval(stageTimer)
    }

    localStageIndex = Math.max(
      localProgressStepNames.indexOf(
        agentStageToSkillStage[currentStage.value] ?? currentStage.value
      ),
      0
    )
    stageTimer = setInterval(() => {
      if (!loading.value) return
      localStageIndex = Math.min(
        localStageIndex + 1,
        localProgressStepNames.length - 1
      )
      setCurrentStage(localProgressStepNames[localStageIndex])
    }, 3000)
  }

  async function fetchHealth() {
    const { data } = await agentApi.health()
    healthStatus.value = data.status
    healthModel.value = data.model
    stubMode.value = data.stub_mode
  }

  async function fetchServices() {
    return withBackendAction('서비스 목록 조회', async () => {
      loadingServices.value = true
      try {
        const { data } = await agentApi.services()
        serviceOptions.value = data.services
      } catch {
        addToast('error', '서비스 목록을 불러오지 못했습니다.')
      } finally {
        loadingServices.value = false
      }
    })
  }

  async function fetchPatternOpsSkills() {
    return withBackendAction('PatternOps 조회', async () => {
      loadingPatternOpsSkills.value = true
      try {
        const { data } = await agentApi.patternOpsSkills({ limit: 100 })
        patternOpsSkills.value = data.skills
        patternOpsSkillEdges.value = data.edges
      } catch {
        addToast('error', 'PatternOps Skill Registry를 불러오지 못했습니다.')
      } finally {
        loadingPatternOpsSkills.value = false
      }
    })
  }

  async function fetchRecommendations(serviceName?: string) {
    return withBackendAction('Recommendation 조회', async () => {
      loadingRecommendations.value = true
      try {
        const { data } = await agentApi.recommendations({
          service_name: serviceName || undefined,
          limit: 20
        })
        recommendationHistory.value = data.recommendations
      } catch {
        addToast('error', '저장된 Recommendation 목록을 불러오지 못했습니다.')
      } finally {
        loadingRecommendations.value = false
      }
    })
  }

  async function deleteSavedRecommendation(recommendationId: number) {
    return withBackendAction('Recommendation 삭제', async () => {
      try {
        const { data } = await agentApi.deleteRecommendation(recommendationId)
        if (data.status !== 'deleted') {
          addToast('error', `Recommendation 삭제 대상이 없습니다: ${recommendationId}`)
          return false
        }
        recommendationHistory.value = recommendationHistory.value.filter(
          (item) => item.id !== recommendationId
        )
        addToast('info', `Recommendation 삭제 완료: ${recommendationId}`)
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `Recommendation 삭제 실패: ${error.value}`)
        return false
      }
    })
  }

  async function fetchKnowledgeCards(fingerprint?: string) {
    return withBackendAction('Knowledge Card 조회', async () => {
      loadingKnowledgeCards.value = true
      try {
        const { data } = await agentApi.knowledgeCards({
          fingerprint: fingerprint || undefined,
          limit: 20
        })
        knowledgeCards.value = data.knowledge_cards
      } catch {
        addToast('error', 'Knowledge Card 목록을 불러오지 못했습니다.')
      } finally {
        loadingKnowledgeCards.value = false
      }
    })
  }

  async function fetchExceptionRegistry(fingerprint?: string) {
    return withBackendAction('예외처리 조회', async () => {
      loadingExceptions.value = true
      try {
        const { data } = await agentApi.exceptions({
          fingerprint: fingerprint || undefined,
          limit: 20
        })
        exceptionRegistry.value = data.exceptions
      } catch {
        addToast('error', '예외처리 목록을 불러오지 못했습니다.')
      } finally {
        loadingExceptions.value = false
      }
    })
  }

  async function fetchDuplicatePatternCandidates() {
    return withBackendAction('Duplicate 후보 조회', async () => {
      loadingDuplicatePatternCandidates.value = true
      try {
        const { data } = await agentApi.duplicatePatternCandidates({
          status: 'pending',
          limit: 50
        })
        duplicatePatternCandidates.value = data.candidates
      } catch {
        addToast('error', 'Duplicate pattern 후보를 불러오지 못했습니다.')
      } finally {
        loadingDuplicatePatternCandidates.value = false
      }
    })
  }

  async function approveDuplicatePatternCandidate(candidateKey: string) {
    return withBackendAction('Duplicate 승인', async () => {
      try {
        const { data } = await agentApi.approveDuplicatePatternCandidate(candidateKey)
        applyPatternClusterPartialRefresh(data.partial_refresh)
        duplicatePatternCandidates.value = duplicatePatternCandidates.value.filter(
          (candidate) => candidate.candidate_key !== candidateKey
        )
        const canonical = data.merge?.canonical_fingerprint
        addToast(
          'info',
          canonical
            ? `Duplicate pattern 승인 완료: ${canonical}`
            : `Duplicate pattern 승인 완료: ${candidateKey}`
        )
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `Duplicate pattern 승인 실패: ${error.value}`)
        return false
      }
    })
  }

  async function rejectDuplicatePatternCandidate(candidateKey: string) {
    return withBackendAction('Duplicate 거절', async () => {
      try {
        await agentApi.rejectDuplicatePatternCandidate(candidateKey)
        duplicatePatternCandidates.value = duplicatePatternCandidates.value.filter(
          (candidate) => candidate.candidate_key !== candidateKey
        )
        addToast('info', `Duplicate pattern 거절 완료: ${candidateKey}`)
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `Duplicate pattern 거절 실패: ${error.value}`)
        return false
      }
    })
  }

  async function manualMergeFingerprints(payload: {
    service_name: string
    analysis_date?: string
    fingerprints: string[]
    cause: string
    recommendation: string
    confidence?: string
  }): Promise<FingerprintManualMergeResponse | null> {
    return withBackendAction('Fingerprint 병합', async () => {
      try {
        const { data } = await agentApi.manualMergeFingerprints({
          service_name: payload.service_name,
          analysis_date: payload.analysis_date,
          fingerprints: payload.fingerprints,
          cause: payload.cause,
          recommendation: payload.recommendation,
          confidence: payload.confidence ?? 'HIGH'
        })
        applyPatternClusterPartialRefresh(data.partial_refresh)
        const canonical =
          data.canonical_fingerprint ?? data.merge?.canonical_fingerprint
        if (data.status !== 'merged' || !canonical) {
          const reason = data.merge?.reason ?? '생성된 fingerprint를 확인할 수 없습니다.'
          error.value = reason
          addToast('error', `선택 FP 병합 실패: ${reason}`)
          return null
        }
        addToast('info', `선택 FP 병합 및 Known 등록 완료: ${canonical}`)
        return {
          ...data,
          canonical_fingerprint: canonical
        }
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `선택 FP 병합 실패: ${error.value}`)
        return null
      }
    })
  }

  function startPollingHealth() {
    if (pollTimer) {
      clearInterval(pollTimer)
    }
    pollTimer = setInterval(async () => {
      try {
        await fetchHealth()
      } catch {
        // ignore intermittent health check failures during polling
      }
    }, 5000)
  }

  async function runAnalysis(serviceName: string, analysisDate?: string) {
    selectedServiceName.value = serviceName
    if (analysisDate) selectedAnalysisDate.value = analysisDate
    const streamId = createStreamId()
    const request = buildDefaultRequest(serviceName, analysisDate, streamId)
    const observability = useObservabilityStore()
    observability.beginRun({
      streamId,
      serviceName,
      analysisDate: analysisDate || new Date().toISOString().slice(0, 10)
    })
    loading.value = true
    executionStatus.value = 'running'
    error.value = null
    localProgressStepNames = analysisStepNames
    resetSkillActivityStream(
      serviceName,
      `분석 시작: ${analysisDate || '오늘'}`
    )
    setCurrentStage('Starting execution')
    agentTimeline.value = stepNames.map((name, index) => ({
      name,
      status:
        name === '추천/결과 정리'
          ? 'skipped'
          : index === 0
            ? 'running'
            : 'pending'
    }))
    setCurrentStage(stepNames[0])
    startLocalStageProgress()

    stream = connectExecutionStream(streamId, {
      onStage: (stage) => {
        setCurrentStage(stage, 'sse')
      },
      onSkill: (execution) => {
        appendStreamedSkillExecution(execution)
      },
      onReasoning: (event) => {
        appendReasoningActivity(event, 'sse')
      },
      onTrace: (event) => {
        observability.ingestTraceEvent(streamId, event)
      },
      onPartial: () => {
        appendSkillActivity({
          skill: currentStage.value,
          status: 'running',
          action: '부분 결과 수신',
          detail: '백엔드가 중간 분석 상태를 전송했습니다.',
          source: 'sse'
        })
        addToast('info', '부분 에이전트 결과를 수신했습니다.')
      },
      onComplete: (result) => {
        state.value = result
        markTimelineFromState(result)
        appendPatternOpsExecutionActivities(result)
        appendReasoningActivities(result)
        observability.ingestFinalState(streamId, result)
      },
      onError: (message) => {
        appendSkillActivity({
          skill: currentStage.value,
          status: 'failed',
          action: 'SSE stream 연결 실패',
          detail: message,
          source: 'sse'
        })
        addToast('error', message)
        observability.markConnection(streamId, 'reconnecting')
        stream = null
        startLocalStageProgress()
      }
    })

    if (!stream) {
      observability.markConnection(streamId, 'fallback')
      startPollingHealth()
      addToast(
        'info',
        'SSE를 사용할 수 없어 5초 간격 상태 확인으로 전환했습니다.'
      )
    }

    try {
      const { data } = await agentApi.analyze(request)
      state.value = data.result
      duplicatePatternCandidates.value =
        data.result.evidence.duplicate_pattern_candidates ?? []
      markTimelineFromState(data.result)
      appendPatternOpsExecutionActivities(data.result)
      appendReasoningActivities(data.result)
      observability.ingestFinalState(streamId, data.result)
      executionStatus.value =
        data.result.decisions.failures.length > 0 ? 'failed' : 'completed'
      lastExecutionAt.value = new Date().toISOString()
      await fetchHealth()
      await fetchRecommendations(serviceName)
      await fetchDuplicatePatternCandidates()
      await fetchPatternOpsSkills()
    } catch (caught) {
      executionStatus.value = 'failed'
      error.value = (caught as Error).message
      currentExecutionLog.value = `분석 실패: ${error.value}`
      appendSkillActivity({
        skill: currentStage.value,
        status: 'failed',
        action: '분석 실패',
        detail: error.value ?? undefined,
        source: 'backend-result'
      })
      observability.markRunStatus(streamId, 'failed')
      addToast('error', `분석 실패: ${error.value}`)
    } finally {
      loading.value = false
      closeStreamAndPolling()
    }
  }

  async function runClusterRecommendation(
    serviceName: string,
    fingerprint: string,
    analysisDate?: string
  ) {
    if (recommendationGeneratingFingerprint.value) {
      addToast(
        'info',
        `Recommendation 생성이 이미 진행중입니다: ${recommendationGeneratingFingerprint.value}`
      )
      return false
    }
    recommendationGeneratingFingerprint.value = fingerprint
    executionStatus.value = 'running'
    error.value = null
    localProgressStepNames = ['임베딩/유사 FP 검색', '추천/결과 정리']
    resetSkillActivityStream(
      serviceName,
      `선택 fingerprint 추천 생성: ${fingerprint}`
    )
    setCurrentStage('임베딩/유사 FP 검색')
    agentTimeline.value = stepNames.map((name) => ({
      name,
      status: ['임베딩/유사 FP 검색', '추천/결과 정리'].includes(name)
        ? 'running'
        : 'skipped'
    }))

    // Dedicated Observability run + SSE stream for this recommendation, kept
    // separate from the /analyze stream so the two never collide.
    const recStreamId = createStreamId()
    const observability = useObservabilityStore()
    observability.beginRun({
      streamId: recStreamId,
      serviceName,
      analysisDate: analysisDate || new Date().toISOString().slice(0, 10),
      operation: 'recommendation',
      fingerprint
    })
    let recStream = connectExecutionStream(recStreamId, {
      onStage: (stage) => setCurrentStage(stage, 'sse'),
      onSkill: (execution) => appendStreamedSkillExecution(execution),
      onReasoning: (event) => appendReasoningActivity(event, 'sse'),
      onTrace: (event) => observability.ingestTraceEvent(recStreamId, event),
      onPartial: () => {},
      onComplete: (result) => observability.ingestFinalState(recStreamId, result),
      onError: (message) => {
        observability.markConnection(recStreamId, 'reconnecting')
        addToast('error', message)
        recStream = null
      }
    })
    if (!recStream) {
      observability.markConnection(recStreamId, 'fallback')
    }

    return withBackendAction('Recommendation 생성', async () => {
      try {
        // Request the backend to execute the downstream recommendation slice for the selected fingerprint.
        const { data } = await agentApi.recommendationForFingerprint({
          service_name: serviceName,
          fingerprint,
          analysis_date: analysisDate || undefined,
          stream_id: recStreamId
        })
        if (state.value) {
          state.value = {
            ...state.value,
            assessment: data.result.assessment,
            decisions: data.result.decisions,
            final: {
              ...state.value.final,
              ...data.result.final
            }
          }
        } else {
          state.value = data.result
        }
        markTimelineFromState(data.result)
        appendPatternOpsExecutionActivities(data.result)
        appendReasoningActivities(data.result)
        // REST fallback: merge the authoritative trace regardless of SSE state.
        observability.ingestFinalState(recStreamId, data.result)
        executionStatus.value =
          data.result.decisions.failures.length > 0 ? 'failed' : 'completed'
        setCurrentStage('Completed')
        lastExecutionAt.value = new Date().toISOString()
        await fetchRecommendations(serviceName)
        await fetchPatternOpsSkills()
        addToast('info', `추천 결과 업데이트 완료: ${fingerprint}`)
      } catch (caught) {
        executionStatus.value = 'failed'
        error.value = errorMessage(caught)
        currentExecutionLog.value = `추천 업데이트 실패: ${error.value}`
        appendSkillActivity({
          skill: currentStage.value,
          status: 'failed',
          action: '추천 업데이트 실패',
          detail: error.value ?? undefined,
          source: 'backend-result'
        })
        observability.markRunStatus(recStreamId, 'failed')
        addToast('error', `추천 업데이트 실패: ${error.value}`)
        return false
      } finally {
        recommendationGeneratingFingerprint.value = null
        if (recStream) {
          recStream.close()
          recStream = null
        }
      }
    })
  }

  async function saveKnownPattern(
    fingerprint: string,
    cause: string,
    recommendation: string,
    serviceName = ''
  ) {
    return withBackendAction('Known Pattern 저장', async () => {
      try {
        const { data } = await agentApi.saveKnownPattern({
          fingerprint,
          service_name: serviceName,
          category: 'Manual',
          sub_category: 'Known Pattern',
          cause,
          recommendation,
          confidence: 'HIGH'
        })
        applyPatternClusterPartialRefresh(data.partial_refresh)
        addToast('info', `Known Pattern 저장 완료: ${data.fingerprint}`)
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `Known Pattern 저장 실패: ${error.value}`)
        return false
      }
    })
  }

  async function suggestPatternRule(cluster: string, message: string) {
    return withBackendAction('Pattern Rule 제안', async () => {
      try {
        const { data } = await agentApi.suggestPatternRule({ cluster, message })
        return data
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `Pattern Rule 제안 실패: ${error.value}`)
        return null
      }
    })
  }

  async function savePatternRule(
    name: string,
    matchRegex: string,
    template: string
  ) {
    return withBackendAction('Pattern Rule 저장', async () => {
      try {
        const { data } = await agentApi.savePatternRule({
          name,
          match_regex: matchRegex,
          template,
          enabled: true,
          priority: 100
        })
        addToast('info', `Pattern Rule 저장 완료: #${data.id}`)
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `Pattern Rule 저장 실패: ${error.value}`)
        return false
      }
    })
  }

  async function saveCurrentRecommendation(serviceName: string) {
    const recommendation = state.value?.final.generated_answer
    const currentState = state.value
    if (!currentState || !recommendation) {
      addToast('error', '저장할 Recommendation이 없습니다.')
      return false
    }

    return withBackendAction('Recommendation 저장', async () => {
      try {
        const { data } = await agentApi.saveRecommendation({
          request_id: currentState.request_id,
          service_name: serviceName,
          goal: currentState.goal,
          executive_summary: currentState.final.executive_summary ?? '',
          recommendation,
          recommended_actions: currentState.final.recommended_actions ?? [],
          verification_steps: currentState.final.verification_steps ?? [],
          evidence_bundle: currentState.final.evidence_bundle ?? {},
          risk_score: currentState.assessment.risk_score,
          confidence: currentState.assessment.confidence
        })
        currentState.final.saved_recommendation_id = data.id
        addToast('info', `Recommendation 저장 완료: ${data.id}`)
        await fetchRecommendations(serviceName)
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `Recommendation 저장 실패: ${error.value}`)
        return false
      }
    })
  }

  async function approveCurrentRecommendation(draft: KnowledgeCardApprovalDraft) {
    const fingerprint = currentRecommendationFingerprint.value
    if (!fingerprint || !draft.recommendation.trim()) {
      addToast('error', '승인할 Recommendation 또는 fingerprint가 없습니다.')
      return false
    }
    if (!draft.resolutionMethod.trim()) {
      addToast('error', 'Knowledge Card 해결 방법을 입력해주세요.')
      return false
    }

    return withBackendAction('Recommendation 승인', async () => {
      try {
        const { data } = await agentApi.approveRecommendation({
          fingerprint,
          cause: draft.cause.trim() || '-',
          recommendation: draft.recommendation.trim(),
          resolution_method: draft.resolutionMethod.trim(),
          action: 'approved',
          confidence: draft.confidence.trim() || currentRecommendationConfidence.value
        })
        addToast('info', `Recommendation 저장 승인 완료: ${data.card_id}`)
        await fetchKnowledgeCards(fingerprint)
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `Recommendation 저장 실패: ${error.value}`)
        return false
      }
    })
  }

  async function registerCurrentException(reason: string) {
    const fingerprint = currentRecommendationFingerprint.value
    if (!fingerprint) {
      addToast('error', '예외처리할 fingerprint가 없습니다.')
      return false
    }

    return withBackendAction('예외처리 등록', async () => {
      try {
        await agentApi.registerException({ fingerprint, reason })
        addToast('info', `예외처리 승인 완료: ${fingerprint}`)
        await fetchExceptionRegistry(fingerprint)
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `예외처리 실패: ${error.value}`)
        return false
      }
    })
  }

  function applyAcceptedNormalToClusters(
    fingerprint: string,
    reason: string,
    patternId?: number
  ) {
    const clusters = state.value?.evidence.clusters
    if (!clusters) return
    for (const cluster of clusters) {
      if (cluster.cluster !== fingerprint) continue
      cluster.accepted_normal = true
      cluster.accepted_normal_reason = reason
      cluster.accepted_normal_status = 'active'
      if (patternId !== undefined) cluster.accepted_normal_id = patternId
    }
  }

  function clearAcceptedNormalFromClusters(fingerprint: string) {
    const clusters = state.value?.evidence.clusters
    if (!clusters) return
    for (const cluster of clusters) {
      if (cluster.cluster !== fingerprint) continue
      cluster.accepted_normal = false
      cluster.accepted_normal_reason = ''
      cluster.accepted_normal_status = ''
      cluster.accepted_normal_id = ''
    }
  }

  async function registerAcceptedNormalPattern(payload: {
    fingerprint: string
    reason: string
    serviceName?: string
    anomalyType?: string
    maxAllowedMultiplier?: number
    maxAllowedCount?: number | null
  }) {
    const fingerprint = payload.fingerprint.trim()
    if (!fingerprint) {
      addToast('error', '정상 편입할 fingerprint가 없습니다.')
      return false
    }

    return withBackendAction('정상 편입 등록', async () => {
      try {
        const { data } = await agentApi.registerAcceptedNormal({
          fingerprint,
          reason: payload.reason,
          service_name: payload.serviceName ?? '',
          anomaly_type: payload.anomalyType ?? '',
          max_allowed_multiplier: payload.maxAllowedMultiplier ?? 1.5,
          max_allowed_count: payload.maxAllowedCount ?? null
        })
        applyAcceptedNormalToClusters(fingerprint, payload.reason, data.id)
        addToast(
          'info',
          `정상 편입(Accepted Normal) 승인 완료: ${fingerprint}. 다음 분석 실행부터 anomaly 집계에서 제외됩니다.`
        )
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `정상 편입 실패: ${error.value}`)
        return false
      }
    })
  }

  async function revokeAcceptedNormalPattern(payload: {
    fingerprint: string
    patternId?: number | string
  }) {
    const fingerprint = payload.fingerprint.trim()
    if (!fingerprint) {
      addToast('error', '지정 해지할 fingerprint가 없습니다.')
      return false
    }

    return withBackendAction('정상 편입 해지', async () => {
      try {
        let patternId = Number(payload.patternId)
        if (!Number.isFinite(patternId) || patternId <= 0) {
          const { data } = await agentApi.acceptedNormalPatterns({
            fingerprint,
            status: 'active',
            limit: 1
          })
          patternId = Number(data.patterns[0]?.id)
        }
        if (!Number.isFinite(patternId) || patternId <= 0) {
          addToast('error', `활성 정상 편입 규칙을 찾을 수 없습니다: ${fingerprint}`)
          return false
        }
        await agentApi.revokeAcceptedNormal(patternId)
        clearAcceptedNormalFromClusters(fingerprint)
        addToast(
          'info',
          `정상 편입 해지 완료: ${fingerprint}. 다음 분석 실행부터 다시 anomaly로 탐지됩니다.`
        )
        return true
      } catch (caught) {
        error.value = (caught as Error).message
        addToast('error', `정상 편입 해지 실패: ${error.value}`)
        return false
      }
    })
  }

  return {
    executionStatus,
    currentStage,
    currentExecutionLog,
    lastExecutionAt,
    healthModel,
    healthStatus,
    stubMode,
    loading,
    loadingServices,
    loadingRecommendations,
    loadingKnowledgeCards,
    loadingExceptions,
    loadingDuplicatePatternCandidates,
    loadingPatternOpsSkills,
    recommendationGeneratingFingerprint,
    backendActionPending,
    backendActionLabel,
    selectedServiceName,
    selectedAnalysisDate,
    error,
    state,
    activeTrajectoryTab,
    selectedRecFMTrajectoryId,
    selectedRecFMHorizon,
    recommendationHistory,
    knowledgeCards,
    exceptionRegistry,
    duplicatePatternCandidates,
    skillActivityStream,
    currentSkillActivity,
    patternOpsSkills,
    patternOpsSkillEdges,
    serviceOptions,
    toasts,
    agentTimeline,
    riskClassification,
    overview,
    skillOpsOverview,
    patternOpsSkillExecutions,
    patternOpsSkillPlan,
    patternOpsValidatorResults,
    recommendationSummary,
    currentRecommendationFingerprint,
    currentRecommendationCause,
    currentRecommendationConfidence,
    fetchHealth,
    fetchServices,
    fetchPatternOpsSkills,
    fetchRecommendations,
    deleteSavedRecommendation,
    fetchKnowledgeCards,
    fetchExceptionRegistry,
    fetchDuplicatePatternCandidates,
    approveDuplicatePatternCandidate,
    rejectDuplicatePatternCandidate,
    manualMergeFingerprints,
    saveKnownPattern,
    suggestPatternRule,
    savePatternRule,
    saveCurrentRecommendation,
    approveCurrentRecommendation,
    registerCurrentException,
    registerAcceptedNormalPattern,
    revokeAcceptedNormalPattern,
    runAnalysis,
    runClusterRecommendation
  }
})
