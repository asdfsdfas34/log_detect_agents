import type { AnalyzeResponse, SharedState } from '@/types/agentTypes'

interface StreamHandlers {
  onStage: (stage: string) => void
  onPartial: (statePatch: Partial<SharedState>) => void
  onComplete: (result: SharedState) => void
  onError: (message: string) => void
}

export function connectExecutionStream(handlers: StreamHandlers): EventSource | null {
  const endpoint = import.meta.env.VITE_ANALYZE_SSE_URL
  if (!endpoint) {
    return null
  }

  const source = new EventSource(endpoint)

  source.addEventListener('stage', (event: MessageEvent<string>) => {
    handlers.onStage(event.data)
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

  source.onerror = () => {
    handlers.onError('SSE stream connection failed')
    source.close()
  }

  return source
}
