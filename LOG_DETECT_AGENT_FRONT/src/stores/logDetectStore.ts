import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { agentApi } from '@/api/agentApi'
import { connectExecutionStream } from '@/services/streamingService'
import type {
  AgentStepStatus,
  AnalyzeRequest,
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
  'ImpactEvaluationAgent',
  'KnowledgeBaseRAGAgent',
  'RecommendationAgent'
]

function buildDefaultRequest(
  serviceName: string,
  analysisDate?: string
): AnalyzeRequest {
  return {
    service_name: serviceName,
    goal: `${serviceName} service log anomaly investigation`,
    save_to_chromadb: true,
    analysis_date: analysisDate || undefined
  }
}

export const useLogDetectStore = defineStore('logDetect', () => {
  const executionStatus = ref<ExecutionStatus>('idle')
  const currentStage = ref<string>('Not started')
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
  const error = ref<string | null>(null)
  const serviceOptions = ref<string[]>([])
  const state = ref<SharedState | null>(null)
  const recommendationHistory = ref<RecommendationHistoryItem[]>([])
  const knowledgeCards = ref<KnowledgeCardItem[]>([])
  const exceptionRegistry = ref<ExceptionRegistryItem[]>([])
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
    currentStage.value = current ? current.name : 'Completed'
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
    currentStage.value = 'Starting execution'
    agentTimeline.value = stepNames.map((name, index) => ({
      name,
      status: index === 0 ? 'running' : 'pending'
    }))

    stream = connectExecutionStream({
      onStage: (stage) => {
        currentStage.value = stage
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
      markTimelineFromState(data.result)
      executionStatus.value =
        data.result.decisions.failures.length > 0 ? 'failed' : 'completed'
      lastExecutionAt.value = new Date().toISOString()
      await fetchHealth()
      await fetchRecommendations(serviceName)
      await fetchLangSmithRuns()
    } catch (caught) {
      executionStatus.value = 'failed'
      error.value = (caught as Error).message
      addToast('error', `Analysis failed: ${error.value}`)
    } finally {
      loading.value = false
      closeStreamAndPolling()
    }
  }

  async function runClusterRecommendation(
    serviceName: string,
    fingerprint: string
  ) {
    executionStatus.value = 'running'
    error.value = null
    currentStage.value = 'ImpactEvaluationAgent'
    agentTimeline.value = stepNames.map((name) => ({
      name,
      status: [
        'ImpactEvaluationAgent',
        'KnowledgeBaseRAGAgent',
        'RecommendationAgent'
      ].includes(name)
        ? 'running'
        : 'skipped'
    }))

    try {
      // Request the backend to execute the downstream recommendation slice for the selected fingerprint.
      const { data } = await agentApi.recommendationForFingerprint({
        service_name: serviceName,
        fingerprint
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
      currentStage.value = 'Completed'
      lastExecutionAt.value = new Date().toISOString()
      await fetchRecommendations(serviceName)
      await fetchLangSmithRuns()
      addToast('info', `Updated recommendations for ${fingerprint}`)
    } catch (caught) {
      executionStatus.value = 'failed'
      error.value = (caught as Error).message
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
    error,
    state,
    recommendationHistory,
    knowledgeCards,
    exceptionRegistry,
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
    saveKnownPattern,
    saveCurrentRecommendation,
    approveCurrentRecommendation,
    registerCurrentException,
    runAnalysis,
    runClusterRecommendation
  }
})
