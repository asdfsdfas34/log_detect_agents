import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { agentApi } from '@/api/agentApi'
import { connectExecutionStream } from '@/services/streamingService'
import type {
  AgentStepStatus,
  AnalyzeRequest,
  DuplicatePatternCandidate,
  ExceptionRegistryItem,
  ExecutionStatus,
  KnowledgeCardItem,
  LangSmithRunItem,
  RecommendationHistoryItem,
  SharedState
} from '@/types/agentTypes'

const stepNames = [
  'OrchestratorAgent',
  'LogCollectorAgent',
  'LogAnalysisAgent',
  'AnomalyDetectionAgent',
  'KnowledgeBaseRAGAgent',
  'RecommendationAgent'
]

const stepLogMessages: Record<string, string> = {
  'Starting execution': '분석 실행을 준비하고 있습니다.',
  OrchestratorAgent:
    'OrchestratorAgent: 요청 범위와 이전 실행 상태를 확인하고 다음에 실행할 agent를 결정하고 있습니다.',
  LogCollectorAgent:
    'LogCollectorAgent: 선택한 서비스의 원천 로그를 가져오고 분석 가능한 형태로 정규화하고 있습니다.',
  LogAnalysisAgent:
    'LogAnalysisAgent: 로그 메시지를 fingerprint 단위로 묶고 Known Pattern 및 신규 패턴 여부를 분석하고 있습니다.',
  AnomalyDetectionAgent:
    'AnomalyDetectionAgent: 발생 빈도, 심각도, 시간 분포를 비교해 이상 징후와 장애 가능성을 탐지하고 있습니다.',
  KnowledgeBaseRAGAgent:
    'KnowledgeBaseRAGAgent: 유사 분석 이력, Knowledge Card, 예외 처리 정보를 조회해 판단 근거를 보강하고 있습니다.',
  RecommendationAgent:
    'RecommendationAgent: 분석 근거를 종합해 영향 범위, 조치 방향, 재발 방지 권고안을 정리하고 있습니다.',
  Completed: '멀티 에이전트 분석이 완료되었습니다.'
}

function buildDefaultRequest(
  serviceName: string,
  analysisDate?: string
): AnalyzeRequest {
  return {
    service_name: serviceName,
    goal: `${serviceName} service log anomaly investigation`,
    save_to_chromadb: true,
    analysis_date: analysisDate || undefined,
    include_similar_clusters: false
  }
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
  const loadingLangSmithRuns = ref(false)
  const loadingDuplicatePatternCandidates = ref(false)
  const error = ref<string | null>(null)
  const serviceOptions = ref<string[]>([])
  const state = ref<SharedState | null>(null)
  const recommendationHistory = ref<RecommendationHistoryItem[]>([])
  const knowledgeCards = ref<KnowledgeCardItem[]>([])
  const exceptionRegistry = ref<ExceptionRegistryItem[]>([])
  const duplicatePatternCandidates = ref<DuplicatePatternCandidate[]>([])
  const langSmithRuns = ref<LangSmithRunItem[]>([])
  const langSmithStatus = ref<{
    enabled: boolean
    project: string
    source: string
    error?: string | null
  }>({ enabled: false, project: 'log-detect-agents', source: 'local' })
  const toasts = ref<
    Array<{ id: number; level: 'info' | 'error'; message: string }>
  >([])
  const agentTimeline = ref<AgentStepStatus[]>(
    stepNames.map((name) => ({ name, status: 'pending' }))
  )
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let stageTimer: ReturnType<typeof setInterval> | null = null
  let localStageIndex = 0
  let stream: EventSource | null = null

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

  function addToast(level: 'info' | 'error', message: string) {
    const id = Date.now() + Math.floor(Math.random() * 1000)
    toasts.value.push({ id, level, message })
    setTimeout(() => {
      toasts.value = toasts.value.filter((item) => item.id !== id)
    }, 3500)
  }

  function markTimelineFromState(result: SharedState) {
    const run = new Set(result.decisions.agents_run)
    const skipped = new Set(result.decisions.skipped_agents)
    const failed = new Set(result.decisions.failures.map((f) => f.node))

    agentTimeline.value = stepNames.map((name) => {
      if (failed.has(name)) return { name, status: 'failed' }
      if (run.has(name)) return { name, status: 'completed' }
      if (skipped.has(name)) return { name, status: 'skipped' }
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

  function setCurrentStage(stage: string) {
    currentStage.value = stage
    currentExecutionLog.value =
      stepLogMessages[stage] || `${stage}: 현재 단계를 실행하고 있습니다.`

    const activeIndex = stepNames.indexOf(stage)
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

    localStageIndex = Math.max(stepNames.indexOf(currentStage.value), 0)
    stageTimer = setInterval(() => {
      if (!loading.value) return
      localStageIndex = Math.min(localStageIndex + 1, stepNames.length - 1)
      setCurrentStage(stepNames[localStageIndex])
    }, 3000)
  }

  async function fetchHealth() {
    const { data } = await agentApi.health()
    healthStatus.value = data.status
    healthModel.value = data.model
    stubMode.value = data.stub_mode
  }

  async function fetchServices() {
    loadingServices.value = true
    try {
      const { data } = await agentApi.services()
      serviceOptions.value = data.services
    } catch {
      addToast('error', '서비스 목록을 불러오지 못했습니다.')
    } finally {
      loadingServices.value = false
    }
  }

  async function fetchLangSmithRuns() {
    loadingLangSmithRuns.value = true
    try {
      const { data } = await agentApi.langSmithRuns({ limit: 30 })
      langSmithRuns.value = data.runs
      langSmithStatus.value = {
        enabled: data.enabled,
        project: data.project,
        source: data.source,
        error: data.error
      }
    } catch {
      addToast('error', 'LangSmith 로그를 불러오지 못했습니다.')
    } finally {
      loadingLangSmithRuns.value = false
    }
  }

  async function fetchRecommendations(serviceName?: string) {
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
  }

  async function deleteSavedRecommendation(recommendationId: number) {
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
  }

  async function fetchKnowledgeCards(fingerprint?: string) {
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
  }

  async function fetchExceptionRegistry(fingerprint?: string) {
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
  }

  async function fetchDuplicatePatternCandidates() {
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
  }

  async function approveDuplicatePatternCandidate(candidateKey: string) {
    try {
      const { data } = await agentApi.approveDuplicatePatternCandidate(candidateKey)
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
  }

  async function rejectDuplicatePatternCandidate(candidateKey: string) {
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
  }

  async function manualMergeFingerprints(payload: {
    service_name: string
    fingerprints: string[]
    cause: string
    recommendation: string
    confidence?: string
    analysisDate?: string
  }) {
    try {
      const { data } = await agentApi.manualMergeFingerprints({
        service_name: payload.service_name,
        fingerprints: payload.fingerprints,
        cause: payload.cause,
        recommendation: payload.recommendation,
        confidence: payload.confidence ?? 'HIGH'
      })
      const canonical = data.canonical_fingerprint ?? data.merge?.canonical_fingerprint
      addToast(
        'info',
        canonical
          ? `선택 FP 병합 및 Known 등록 완료: ${canonical}`
          : '선택 FP 병합 및 Known 등록 완료'
      )
      await runAnalysis(payload.service_name, payload.analysisDate)
      return true
    } catch (caught) {
      error.value = (caught as Error).message
      addToast('error', `선택 FP 병합 실패: ${error.value}`)
      return false
    }
  }

  function startPollingHealth() {
    closeStreamAndPolling()
    pollTimer = setInterval(async () => {
      try {
        await fetchHealth()
      } catch {
        // ignore intermittent health check failures during polling
      }
    }, 5000)
  }

  async function runAnalysis(serviceName: string, analysisDate?: string) {
    const request = buildDefaultRequest(serviceName, analysisDate)
    loading.value = true
    executionStatus.value = 'running'
    error.value = null
    setCurrentStage('Starting execution')
    agentTimeline.value = stepNames.map((name, index) => ({
      name,
      status: index === 0 ? 'running' : 'pending'
    }))
    setCurrentStage(stepNames[0])
    startLocalStageProgress()

    stream = connectExecutionStream({
      onStage: (stage) => {
        setCurrentStage(stage)
      },
      onPartial: () => {
        addToast('info', 'Received partial agent output')
      },
      onComplete: (result) => {
        state.value = result
        markTimelineFromState(result)
      },
      onError: (message) => {
        addToast('error', message)
        stream = null
        startLocalStageProgress()
      }
    })

    if (!stream) {
      startPollingHealth()
      addToast(
        'info',
        'SSE unavailable: switched to 5s health polling fallback'
      )
    }

    try {
      const { data } = await agentApi.analyze(request)
      state.value = data.result
      duplicatePatternCandidates.value =
        data.result.evidence.duplicate_pattern_candidates ?? []
      markTimelineFromState(data.result)
      executionStatus.value =
        data.result.decisions.failures.length > 0 ? 'failed' : 'completed'
      lastExecutionAt.value = new Date().toISOString()
      await fetchHealth()
      await fetchRecommendations(serviceName)
      await fetchDuplicatePatternCandidates()
      await fetchLangSmithRuns()
    } catch (caught) {
      executionStatus.value = 'failed'
      error.value = (caught as Error).message
      currentExecutionLog.value = `분석 실패: ${error.value}`
      addToast('error', `Analysis failed: ${error.value}`)
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
    executionStatus.value = 'running'
    error.value = null
    setCurrentStage('KnowledgeBaseRAGAgent')
    agentTimeline.value = stepNames.map((name) => ({
      name,
      status: ['KnowledgeBaseRAGAgent', 'RecommendationAgent'].includes(name)
        ? 'running'
        : 'skipped'
    }))

    try {
      // Request the backend to execute the downstream recommendation slice for the selected fingerprint.
      const { data } = await agentApi.recommendationForFingerprint({
        service_name: serviceName,
        fingerprint,
        analysis_date: analysisDate || undefined
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
      executionStatus.value =
        data.result.decisions.failures.length > 0 ? 'failed' : 'completed'
      setCurrentStage('Completed')
      lastExecutionAt.value = new Date().toISOString()
      await fetchRecommendations(serviceName)
      await fetchLangSmithRuns()
      addToast('info', `Updated recommendations for ${fingerprint}`)
    } catch (caught) {
      executionStatus.value = 'failed'
      error.value = (caught as Error).message
      currentExecutionLog.value = `Recommendation update 실패: ${error.value}`
      addToast('error', `Recommendation update failed: ${error.value}`)
    }
  }

  async function saveKnownPattern(
    fingerprint: string,
    cause: string,
    recommendation: string
  ) {
    try {
      const { data } = await agentApi.saveKnownPattern({
        fingerprint,
        category: 'Manual',
        sub_category: 'Known Pattern',
        cause,
        recommendation,
        confidence: 'HIGH'
      })
      addToast('info', `Known Pattern 저장 완료: ${data.fingerprint}`)
      return true
    } catch (caught) {
      error.value = (caught as Error).message
      addToast('error', `Known Pattern 저장 실패: ${error.value}`)
      return false
    }
  }

  async function suggestPatternRule(cluster: string, message: string) {
    try {
      const { data } = await agentApi.suggestPatternRule({ cluster, message })
      return data
    } catch (caught) {
      error.value = (caught as Error).message
      addToast('error', `Pattern Rule 제안 실패: ${error.value}`)
      return null
    }
  }

  async function savePatternRule(
    name: string,
    matchRegex: string,
    template: string
  ) {
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
  }

  async function saveCurrentRecommendation(serviceName: string) {
    const recommendation = state.value?.final.generated_answer
    if (!state.value || !recommendation) {
      addToast('error', '저장할 Recommendation이 없습니다.')
      return false
    }

    try {
      const { data } = await agentApi.saveRecommendation({
        request_id: state.value.request_id,
        service_name: serviceName,
        goal: state.value.goal,
        executive_summary: state.value.final.executive_summary ?? '',
        recommendation,
        recommended_actions: state.value.final.recommended_actions ?? [],
        verification_steps: state.value.final.verification_steps ?? [],
        evidence_bundle: state.value.final.evidence_bundle ?? {},
        risk_score: state.value.assessment.risk_score,
        confidence: state.value.assessment.confidence
      })
      state.value.final.saved_recommendation_id = data.id
      addToast('info', `Recommendation 저장 완료: ${data.id}`)
      await fetchRecommendations(serviceName)
      return true
    } catch (caught) {
      error.value = (caught as Error).message
      addToast('error', `Recommendation 저장 실패: ${error.value}`)
      return false
    }
  }

  async function approveCurrentRecommendation(resolutionMethod: string) {
    const fingerprint = currentRecommendationFingerprint.value
    const recommendation = state.value?.final.generated_answer
    if (!fingerprint || !recommendation) {
      addToast('error', '승인할 Recommendation 또는 fingerprint가 없습니다.')
      return false
    }

    try {
      const { data } = await agentApi.approveRecommendation({
        fingerprint,
        cause: currentRecommendationCause.value || '-',
        recommendation,
        resolution_method: resolutionMethod,
        action: 'approved',
        confidence: currentRecommendationConfidence.value
      })
      addToast('info', `Recommendation 저장 승인 완료: ${data.card_id}`)
      await fetchKnowledgeCards(fingerprint)
      return true
    } catch (caught) {
      error.value = (caught as Error).message
      addToast('error', `Recommendation 저장 실패: ${error.value}`)
      return false
    }
  }

  async function registerCurrentException(reason: string) {
    const fingerprint = currentRecommendationFingerprint.value
    if (!fingerprint) {
      addToast('error', '예외처리할 fingerprint가 없습니다.')
      return false
    }

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
    loadingLangSmithRuns,
    loadingDuplicatePatternCandidates,
    error,
    state,
    recommendationHistory,
    knowledgeCards,
    exceptionRegistry,
    duplicatePatternCandidates,
    langSmithRuns,
    langSmithStatus,
    serviceOptions,
    toasts,
    agentTimeline,
    riskClassification,
    overview,
    recommendationSummary,
    currentRecommendationFingerprint,
    fetchHealth,
    fetchServices,
    fetchLangSmithRuns,
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
    runAnalysis,
    runClusterRecommendation
  }
})
