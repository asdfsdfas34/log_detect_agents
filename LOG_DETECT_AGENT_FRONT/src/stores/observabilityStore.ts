import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import type {
  AgentTraceEvent,
  ObservabilityConnectionStatus,
  ObservabilityOperation,
  ObservabilityRun,
  ObservabilityRunStatus,
  SharedState
} from '@/types/agentTypes'

/**
 * Dedicated trace state for the Agent Process Observability screen. Kept
 * separate from logDetectStore so switching screens never mutates or refetches
 * /analyze evidence. The store is fed by the shared SSE connection (via
 * logDetectStore handlers) and by completed REST results.
 */
export const useObservabilityStore = defineStore('observability', () => {
  // Runs keyed by stream_id (stable for the lifetime of one analysis request).
  const runs = ref<Record<string, ObservabilityRun>>({})
  const activeStreamId = ref<string | null>(null)
  const selectedStreamId = ref<string | null>(null)
  const selectedEventId = ref<string | null>(null)

  const runList = computed<ObservabilityRun[]>(() =>
    Object.values(runs.value).sort((left, right) =>
      right.started_at.localeCompare(left.started_at)
    )
  )

  const selectedRun = computed<ObservabilityRun | null>(() => {
    const streamId = selectedStreamId.value ?? activeStreamId.value
    if (!streamId) return null
    return runs.value[streamId] ?? null
  })

  const selectedEvent = computed<AgentTraceEvent | null>(() => {
    const run = selectedRun.value
    if (!run || !selectedEventId.value) return null
    return run.events.find((event) => event.event_id === selectedEventId.value) ?? null
  })

  function beginRun(payload: {
    streamId: string
    serviceName: string
    analysisDate: string
    operation?: ObservabilityOperation
    fingerprint?: string
  }) {
    const now = new Date().toISOString()
    runs.value = {
      ...runs.value,
      [payload.streamId]: {
        request_id: '',
        stream_id: payload.streamId,
        service_name: payload.serviceName,
        analysis_date: payload.analysisDate,
        operation: payload.operation ?? 'analysis',
        fingerprint: payload.fingerprint,
        status: 'running',
        connection: 'connected',
        started_at: now,
        ended_at: null,
        events: []
      }
    }
    activeStreamId.value = payload.streamId
    selectedStreamId.value = payload.streamId
    selectedEventId.value = null
  }

  function ensureRun(streamId: string): ObservabilityRun {
    let run = runs.value[streamId]
    if (!run) {
      const now = new Date().toISOString()
      run = {
        request_id: '',
        stream_id: streamId,
        service_name: '',
        analysis_date: '',
        operation: 'analysis',
        status: 'running',
        connection: 'connected',
        started_at: now,
        ended_at: null,
        events: []
      }
      runs.value = { ...runs.value, [streamId]: run }
    }
    return run
  }

  /** Insert a trace event, deduped by event_id and kept ordered by sequence. */
  function ingestTraceEvent(streamId: string, event: AgentTraceEvent) {
    const run = ensureRun(streamId)
    if (!run.request_id && event.request_id) run.request_id = event.request_id
    if (run.events.some((existing) => existing.event_id === event.event_id)) return
    const next = [...run.events, event].sort((left, right) => left.sequence - right.sequence)
    runs.value = {
      ...runs.value,
      [streamId]: { ...run, events: next }
    }
  }

  function markConnection(
    streamId: string,
    connection: ObservabilityConnectionStatus
  ) {
    const run = runs.value[streamId]
    if (!run) return
    runs.value = { ...runs.value, [streamId]: { ...run, connection } }
  }

  /**
   * Restore/merge the authoritative trace from a completed REST result. Used
   * both on normal completion and as the fallback path when the SSE stream
   * dropped mid-run.
   */
  function ingestFinalState(streamId: string, result: SharedState) {
    const run = ensureRun(streamId)
    const finalEvents =
      result.evidence.agent_trace_events ??
      result.final.evidence_bundle?.agent_trace_events ??
      []
    const byId = new Map<string, AgentTraceEvent>()
    for (const event of run.events) byId.set(event.event_id, event)
    for (const event of finalEvents) byId.set(event.event_id, event)
    const merged = Array.from(byId.values()).sort(
      (left, right) => left.sequence - right.sequence
    )
    const failures = result.decisions.failures.length
    const status: ObservabilityRunStatus = failures > 0 ? 'degraded' : 'completed'
    runs.value = {
      ...runs.value,
      [streamId]: {
        ...run,
        request_id: result.request_id || run.request_id,
        status,
        connection: 'completed',
        ended_at: new Date().toISOString(),
        events: merged
      }
    }
  }

  function markRunStatus(streamId: string, status: ObservabilityRunStatus) {
    const run = runs.value[streamId]
    if (!run) return
    runs.value = {
      ...runs.value,
      [streamId]: {
        ...run,
        status,
        ended_at: status === 'running' ? run.ended_at : new Date().toISOString()
      }
    }
  }

  function selectRun(streamId: string) {
    if (!runs.value[streamId]) return
    selectedStreamId.value = streamId
    selectedEventId.value = null
  }

  function selectEvent(eventId: string | null) {
    selectedEventId.value = eventId
  }

  function reset() {
    runs.value = {}
    activeStreamId.value = null
    selectedStreamId.value = null
    selectedEventId.value = null
  }

  return {
    runs,
    activeStreamId,
    selectedStreamId,
    selectedEventId,
    runList,
    selectedRun,
    selectedEvent,
    beginRun,
    ingestTraceEvent,
    markConnection,
    ingestFinalState,
    markRunStatus,
    selectRun,
    selectEvent,
    reset
  }
})
