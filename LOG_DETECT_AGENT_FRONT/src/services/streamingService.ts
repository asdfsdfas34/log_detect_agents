import type {
  AgentReasoningEvent,
  AgentTraceEvent,
  AnalyzeResponse,
  PatternOpsSkillExecution,
  SharedState
} from '@/types/agentTypes'

interface StreamHandlers {
  onStage: (stage: string) => void
  onSkill: (execution: PatternOpsSkillExecution & { skill_name?: string }) => void
  onReasoning: (event: AgentReasoningEvent) => void
  onTrace?: (event: AgentTraceEvent) => void
  onPartial: (statePatch: Partial<SharedState>) => void
  onComplete: (result: SharedState) => void
  onError: (message: string) => void
}

export function connectExecutionStream(
  streamId: string,
  handlers: StreamHandlers
): EventSource | null {
  const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
  const endpoint = import.meta.env.VITE_ANALYZE_SSE_URL ?? `${baseUrl}/analyze/stream`
  const url = new URL(endpoint, baseUrl)
  url.searchParams.set('stream_id', streamId)

  const source = new EventSource(url.toString())

  source.addEventListener('stage', (event: MessageEvent<string>) => {
    handlers.onStage(event.data)
  })

  source.addEventListener('skill', (event: MessageEvent<string>) => {
    try {
      handlers.onSkill(
        JSON.parse(event.data) as PatternOpsSkillExecution & {
          skill_name?: string
        }
      )
    } catch (error) {
      handlers.onError((error as Error).message)
    }
  })

  source.addEventListener('reasoning', (event: MessageEvent<string>) => {
    try {
      handlers.onReasoning(JSON.parse(event.data) as AgentReasoningEvent)
    } catch (error) {
      handlers.onError((error as Error).message)
    }
  })

  source.addEventListener('trace', (event: MessageEvent<string>) => {
    if (!handlers.onTrace) return
    try {
      handlers.onTrace(JSON.parse(event.data) as AgentTraceEvent)
    } catch (error) {
      handlers.onError((error as Error).message)
    }
  })

  source.addEventListener('partial', (event: MessageEvent<string>) => {
    try {
      handlers.onPartial(JSON.parse(event.data) as Partial<SharedState>)
    } catch (error) {
      handlers.onError((error as Error).message)
    }
  })

  source.addEventListener('final', (event: MessageEvent<string>) => {
    try {
      const payload = JSON.parse(event.data) as AnalyzeResponse | SharedState
      const result = 'result' in payload ? payload.result : payload
      handlers.onComplete(result)
    } catch (error) {
      handlers.onError((error as Error).message)
    }
  })

  source.addEventListener('done', () => {
    source.close()
  })

  source.onerror = () => {
    handlers.onError('SSE stream connection failed')
    source.close()
  }

  return source
}
