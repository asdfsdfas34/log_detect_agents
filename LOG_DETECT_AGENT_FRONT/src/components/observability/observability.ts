import type {
  AgentTraceEvent,
  ObservabilityConnectionStatus,
  ObservabilityRunStatus,
  TraceKind,
  TraceLayer,
  TraceStatus
} from '@/types/agentTypes'

/**
 * Shared, redaction-aware presentation helpers for the Agent Process
 * Observability screen. All labels are Korean and every status is conveyed
 * with both text and an icon (never color alone).
 */

export interface KindMeta {
  label: string
  icon: string
  chip: string
  dot: string
  indent: 0 | 1 | 2
}

const KIND_META: Record<TraceKind, KindMeta> = {
  request: { label: '요청', icon: '📥', chip: 'bg-slate-100 text-slate-700', dot: 'bg-slate-400', indent: 0 },
  planning: { label: 'Planning', icon: '🧭', chip: 'bg-violet-100 text-violet-700', dot: 'bg-violet-500', indent: 0 },
  routing: { label: 'Routing', icon: '🔀', chip: 'bg-indigo-100 text-indigo-700', dot: 'bg-indigo-500', indent: 0 },
  agent: { label: 'Agent', icon: '🤖', chip: 'bg-blue-100 text-blue-700', dot: 'bg-blue-500', indent: 0 },
  skill: { label: 'Skill', icon: '🧩', chip: 'bg-cyan-100 text-cyan-700', dot: 'bg-cyan-500', indent: 1 },
  tool_call: { label: 'Tool Call', icon: '🛠️', chip: 'bg-teal-100 text-teal-700', dot: 'bg-teal-500', indent: 2 },
  observation: { label: 'Observation', icon: '👁️', chip: 'bg-emerald-100 text-emerald-700', dot: 'bg-emerald-500', indent: 2 },
  validation: { label: 'Verification', icon: '✅', chip: 'bg-lime-100 text-lime-700', dot: 'bg-lime-600', indent: 2 },
  retrieval: { label: 'Retrieval', icon: '🔎', chip: 'bg-sky-100 text-sky-700', dot: 'bg-sky-500', indent: 2 },
  persistence: { label: 'Persistence', icon: '💾', chip: 'bg-amber-100 text-amber-700', dot: 'bg-amber-500', indent: 2 },
  llm: { label: 'LLM', icon: '🧠', chip: 'bg-fuchsia-100 text-fuchsia-700', dot: 'bg-fuchsia-500', indent: 2 },
  self_correction: { label: 'Self-Correction', icon: '♻️', chip: 'bg-rose-100 text-rose-700', dot: 'bg-rose-500', indent: 1 },
  quality: { label: 'Quality', icon: '📊', chip: 'bg-rose-100 text-rose-700', dot: 'bg-rose-500', indent: 1 },
  fallback: { label: 'Fallback', icon: '🪂', chip: 'bg-orange-100 text-orange-700', dot: 'bg-orange-500', indent: 1 },
  sse: { label: 'SSE', icon: '📡', chip: 'bg-slate-100 text-slate-700', dot: 'bg-slate-400', indent: 0 }
}

export function kindMeta(kind: TraceKind): KindMeta {
  return KIND_META[kind] ?? KIND_META.request
}

export const KIND_FILTER_OPTIONS: Array<{ value: TraceKind; label: string }> = (
  Object.keys(KIND_META) as TraceKind[]
).map((value) => ({ value, label: KIND_META[value].label }))

const STATUS_META: Record<
  TraceStatus,
  { label: string; icon: string; chip: string }
> = {
  planned: { label: '계획됨', icon: '◻', chip: 'bg-amber-100 text-amber-700' },
  running: { label: '실행 중', icon: '⟳', chip: 'bg-blue-100 text-blue-700' },
  completed: { label: '완료', icon: '✓', chip: 'bg-emerald-100 text-emerald-700' },
  failed: { label: '실패', icon: '✕', chip: 'bg-red-100 text-red-700' },
  skipped: { label: '건너뜀', icon: '⤳', chip: 'bg-slate-200 text-slate-600' }
}

export function statusMeta(status: TraceStatus) {
  return STATUS_META[status] ?? STATUS_META.planned
}

const LAYER_LABELS: Record<TraceLayer, string> = {
  client: '클라이언트',
  api: 'API',
  orchestration: '오케스트레이션',
  agent: 'Agent',
  skill: 'Skill',
  reasoning: '추론',
  data_access: '데이터 접근',
  retrieval: '조회',
  llm: 'LLM',
  persistence: '저장'
}

export function layerLabel(layer: TraceLayer): string {
  return LAYER_LABELS[layer] ?? layer
}

const RUN_STATUS_META: Record<
  ObservabilityRunStatus,
  { label: string; chip: string; icon: string }
> = {
  running: { label: '실행 중', chip: 'bg-blue-100 text-blue-700', icon: '⟳' },
  completed: { label: '완료', chip: 'bg-emerald-100 text-emerald-700', icon: '✓' },
  degraded: { label: '부분 성공', chip: 'bg-amber-100 text-amber-700', icon: '⚠' },
  failed: { label: '실패', chip: 'bg-red-100 text-red-700', icon: '✕' }
}

export function runStatusMeta(status: ObservabilityRunStatus) {
  return RUN_STATUS_META[status] ?? RUN_STATUS_META.running
}

const CONNECTION_META: Record<
  ObservabilityConnectionStatus,
  { label: string; chip: string; icon: string }
> = {
  idle: { label: '대기', chip: 'bg-slate-100 text-slate-600', icon: '○' },
  connected: { label: 'SSE 연결됨', chip: 'bg-emerald-100 text-emerald-700', icon: '●' },
  reconnecting: { label: '재연결 중', chip: 'bg-amber-100 text-amber-700', icon: '◐' },
  fallback: { label: 'REST 폴백', chip: 'bg-amber-100 text-amber-700', icon: '◑' },
  completed: { label: '완료', chip: 'bg-slate-100 text-slate-600', icon: '✓' }
}

export function connectionMeta(status: ObservabilityConnectionStatus) {
  return CONNECTION_META[status] ?? CONNECTION_META.idle
}

/**
 * One logical process step. A start event and its matching completion event
 * (sharing a span_id) collapse into a single node so the timeline updates in
 * place instead of stacking duplicate rows. Start time and duration are kept.
 */
export interface TimelineNode {
  id: string
  representativeEventId: string
  kind: TraceKind
  layer: TraceLayer
  component: string
  agentName: string
  title: string
  summary: string
  status: TraceStatus
  eventType: string
  firstSequence: number
  startedAt: string
  durationMs: number | null
  attempt: number | null
  maxAttempts: number | null
  hasError: boolean
  fallbackUsed: boolean
}

export function collapseBySpan(events: AgentTraceEvent[]): TimelineNode[] {
  const groups = new Map<string, AgentTraceEvent[]>()
  for (const event of events) {
    const key = event.span_id || event.event_id
    const bucket = groups.get(key)
    if (bucket) bucket.push(event)
    else groups.set(key, [event])
  }
  const nodes: TimelineNode[] = []
  for (const bucket of groups.values()) {
    const ordered = [...bucket].sort((left, right) => left.sequence - right.sequence)
    const first = ordered[0]
    const terminal = ordered[ordered.length - 1]
    const duration = ordered.reduce<number | null>(
      (acc, event) => (event.duration_ms != null ? event.duration_ms : acc),
      null
    )
    nodes.push({
      id: first.span_id || first.event_id,
      representativeEventId: terminal.event_id,
      kind: terminal.kind,
      layer: terminal.layer,
      component: terminal.component,
      agentName: terminal.agent_name,
      title: terminal.title,
      summary: terminal.summary,
      status: terminal.status,
      eventType: terminal.event_type,
      firstSequence: first.sequence,
      startedAt: first.timestamp,
      durationMs: duration,
      attempt: terminal.attempt,
      maxAttempts: terminal.max_attempts,
      hasError: ordered.some((event) => event.error != null),
      fallbackUsed: ordered.some((event) => event.fallback_used)
    })
  }
  return nodes.sort((left, right) => left.firstSequence - right.firstSequence)
}

export function formatDuration(durationMs: number | null): string {
  if (durationMs == null) return '—'
  if (durationMs < 1000) return `${durationMs}ms`
  return `${(durationMs / 1000).toFixed(2)}s`
}

export function formatClock(timestamp: string): string {
  const date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) return '—'
  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}

export function elapsedSince(fromIso: string, toIso: string): string {
  const from = new Date(fromIso).getTime()
  const to = new Date(toIso).getTime()
  if (Number.isNaN(from) || Number.isNaN(to)) return '—'
  const seconds = Math.max(0, (to - from) / 1000)
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  return `${minutes}m ${Math.round(seconds % 60)}s`
}

// Process map lanes derived from the reference architecture. Each lane maps to
// one or more trace components so its live status is derived from real events.
export interface ProcessMapNode {
  id: string
  label: string
  lane: string
  components: string[]
  agents: string[]
}

export const PROCESS_MAP_NODES: ProcessMapNode[] = [
  { id: 'api', label: 'FastAPI', lane: 'API', components: ['AnalyzeAPI', 'StreamingService'], agents: ['FastAPI'] },
  { id: 'orchestrator', label: 'Orchestrator', lane: 'LangGraph', components: ['OrchestratorAgent'], agents: ['OrchestratorAgent'] },
  { id: 'collector', label: 'LogCollector', lane: 'LangGraph', components: ['LogCollectorAgent'], agents: ['LogCollectorAgent'] },
  { id: 'analysis', label: 'LogAnalysis', lane: 'LangGraph', components: ['LogAnalysisAgent'], agents: ['LogAnalysisAgent'] },
  { id: 'anomaly', label: 'AnomalyDetection', lane: 'LangGraph', components: ['AnomalyDetectionAgent'], agents: ['AnomalyDetectionAgent'] },
  { id: 'rag', label: 'KnowledgeBaseRAG', lane: 'Service', components: ['KnowledgeBaseRAGAgent'], agents: ['KnowledgeBaseRAGAgent'] },
  { id: 'recommendation', label: 'Recommendation', lane: 'Service', components: ['RecommendationAgent'], agents: ['RecommendationAgent'] },
  { id: 'verification', label: 'PatternVerification', lane: 'Service', components: ['PatternVerification'], agents: ['ScenarioAnalysis'] },
  { id: 'skills', label: 'PatternSkillRunner', lane: 'Service', components: ['PatternSkillRunner', 'SkillValidator'], agents: [] },
  { id: 'sqlite', label: 'SQLite', lane: 'Data', components: ['SQLiteStore'], agents: [] },
  { id: 'chroma', label: 'ChromaDB', lane: 'Data', components: ['ChromaStore'], agents: [] },
  { id: 'openai', label: 'OpenAI', lane: 'Data', components: ['OpenAIClient'], agents: [] }
]

export type ProcessNodeState = 'idle' | 'running' | 'completed' | 'failed'

export function processNodeState(
  node: ProcessMapNode,
  events: AgentTraceEvent[]
): ProcessNodeState {
  const related = events.filter(
    (event) =>
      node.components.includes(event.component) ||
      node.agents.includes(event.agent_name)
  )
  if (!related.length) return 'idle'
  if (related.some((event) => event.status === 'failed')) return 'failed'
  // A `*.started` / `request.accepted` event keeps status `running` even after
  // its paired completion arrives, so "some event is running" would latch the
  // node as running forever. Decide from the most recent event instead: the
  // node is only running if its latest activity has not yet completed.
  const latest = related.reduce((newest, event) =>
    event.sequence > newest.sequence ? event : newest
  )
  if (latest.status === 'running' || latest.status === 'planned') return 'running'
  return 'completed'
}

export const DEPENDENCY_FILTERS: Array<{ value: string; label: string; components: string[] }> = [
  { value: 'sqlite', label: 'SQLite', components: ['SQLiteStore'] },
  { value: 'chroma', label: 'ChromaDB', components: ['ChromaStore'] },
  { value: 'openai', label: 'OpenAI', components: ['OpenAIClient'] }
]
