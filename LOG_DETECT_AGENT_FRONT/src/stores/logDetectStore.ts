import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { agentApi } from '@/api/agentApi'
import { connectExecutionStream } from '@/services/streamingService'
import type {
  AgentStepStatus,
  AnalyzeRequest,
  ExecutionStatus,
  SharedState
} from '@/types/agentTypes'

const stepNames = [
  'OrchestratorAgent',
  'LogCollectorAgent',
  'LogAnalysisAgent',
  'AnomalyDetectionAgent',
  'IncidentCorrelationAgent',
  'ImpactEvaluationAgent',
  'SourceCodeAnalysisAgent',
  'KnowledgeBaseRAGAgent',
  'RecommendationAgent'
]

function buildDefaultRequest(serviceName: string, saveToChromaDb: boolean): AnalyzeRequest {
  return {
    service_name: serviceName,
    goal: `${serviceName} service log anomaly investigation`,
    save_to_chromadb: saveToChromaDb
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
  const error = ref<string | null>(null)
  const serviceOptions = ref<string[]>([])
  const state = ref<SharedState | null>(null)
  const toasts = ref<Array<{ id: number; level: 'info' | 'error'; message: string }>>([])
  const agentTimeline = ref<AgentStepStatus[]>(stepNames.map((name) => ({ name, status: 'pending' })))
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let stream: EventSource | null = null

  const scenarioSummary = computed(() => state.value?.final.evidence_bundle?.summary)
  const recommendationSummary = computed(() => state.value?.final.evidence_bundle?.recommendation)

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
    totalLogs: scenarioSummary.value?.total_logs ?? state.value?.evidence.normalized_logs.length ?? 0,
    totalFingerprints: scenarioSummary.value?.total_fingerprints ?? state.value?.evidence.clusters.length ?? 0,
    knownPatterns: scenarioSummary.value?.known_patterns ?? 0,
    newPatterns: scenarioSummary.value?.new_patterns ?? 0,
    anomaliesDetected: scenarioSummary.value?.anomalies_detected ?? state.value?.evidence.anomalies.length ?? 0,
    exceptionRegisteredCount: scenarioSummary.value?.exception_registered_count ?? 0,
    riskScore: scenarioSummary.value?.risk_score ?? state.value?.assessment.risk_score ?? 0,
    riskLevel: scenarioSummary.value?.risk_level ?? riskClassification.value,
    detectionStatus: scenarioSummary.value?.detection_status ?? 'Not analyzed',
    impactScore: scenarioSummary.value?.risk_score ?? state.value?.assessment.risk_score ?? 0
  }))

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

  async function runAnalysis(serviceName: string, saveToChromaDb: boolean) {
    const request = buildDefaultRequest(serviceName, saveToChromaDb)
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
      addToast('info', 'SSE unavailable: switched to 5s health polling fallback')
    }

    try {
      const { data } = await agentApi.analyze(request)
      state.value = data.result
      markTimelineFromState(data.result)
      executionStatus.value = data.result.decisions.failures.length > 0 ? 'failed' : 'completed'
      lastExecutionAt.value = new Date().toISOString()
      await fetchHealth()
    } catch (caught) {
      executionStatus.value = 'failed'
      error.value = (caught as Error).message
      addToast('error', `Analysis failed: ${error.value}`)
    } finally {
      loading.value = false
      closeStreamAndPolling()
    }
  }

  async function runClusterRecommendation(serviceName: string, fingerprint: string) {
    executionStatus.value = 'running'
    error.value = null
    currentStage.value = 'IncidentCorrelationAgent'
    agentTimeline.value = stepNames.map((name) => ({
      name,
      status: ['IncidentCorrelationAgent', 'ImpactEvaluationAgent', 'KnowledgeBaseRAGAgent', 'RecommendationAgent'].includes(name)
        ? 'running'
        : 'skipped'
    }))

    try {
      // Request the backend to execute the downstream recommendation slice for the selected fingerprint.
      const { data } = await agentApi.recommendationForFingerprint({ service_name: serviceName, fingerprint })
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
      executionStatus.value = data.result.decisions.failures.length > 0 ? 'failed' : 'completed'
      currentStage.value = 'Completed'
      lastExecutionAt.value = new Date().toISOString()
      addToast('info', `Updated recommendations for ${fingerprint}`)
    } catch (caught) {
      executionStatus.value = 'failed'
      error.value = (caught as Error).message
      addToast('error', `Recommendation update failed: ${error.value}`)
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
    error,
    state,
    serviceOptions,
    toasts,
    agentTimeline,
    riskClassification,
    overview,
    recommendationSummary,
    fetchHealth,
    fetchServices,
    runAnalysis,
    runClusterRecommendation
  }
})
