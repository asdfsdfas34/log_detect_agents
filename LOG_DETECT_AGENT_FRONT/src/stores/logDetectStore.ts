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
  'LogCollectorAgent',
  'LogAnalysisAgent',
  'ImpactEvaluationAgent',
  'SourceCodeAnalysisAgent',
  'RecommendationAgent'
]

function buildDefaultRequest(serviceName: string): AnalyzeRequest {
  return {
    service_name: serviceName,
    goal: `${serviceName} service log anomaly investigation`
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
  const error = ref<string | null>(null)
  const state = ref<SharedState | null>(null)
  const toasts = ref<Array<{ id: number; level: 'info' | 'error'; message: string }>>([])
  const agentTimeline = ref<AgentStepStatus[]>(stepNames.map((name) => ({ name, status: 'pending' })))
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let stream: EventSource | null = null

  const riskClassification = computed(() => {
    const score = state.value?.assessment.risk_score ?? 0
    if (score >= 70) return 'High'
    if (score >= 30) return 'Medium'
    return 'Low'
  })

  const overview = computed(() => ({
    totalLogs: state.value?.evidence.normalized_logs.length ?? 0,
    totalAnomalies: state.value?.evidence.anomalies.length ?? 0,
    uniquePatterns: state.value?.evidence.clusters.length ?? 0,
    impactScore: state.value?.assessment.risk_score ?? 0
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

  async function runAnalysis(serviceName: string) {
    const request = buildDefaultRequest(serviceName)
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

  return {
    executionStatus,
    currentStage,
    lastExecutionAt,
    healthModel,
    healthStatus,
    stubMode,
    loading,
    error,
    state,
    toasts,
    agentTimeline,
    riskClassification,
    overview,
    fetchHealth,
    runAnalysis
  }
})
