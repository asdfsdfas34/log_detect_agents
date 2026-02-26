export type ConfidenceLevel = 'low' | 'mid' | 'high'

export interface Scope {
  systems: string[]
  time_range: {
    from: string
    to: string
  }
  filters: Record<string, unknown>
}

export interface AnalyzeRequest {
  goal: string
  scope: Scope
}

export interface NormalizedLog {
  timestamp?: string
  system?: string
  level?: string
  message?: string
  stack_trace?: string
}

export interface Anomaly {
  system?: string
  severity?: string
  pattern?: string
  message?: string
}

export interface Cluster {
  cluster: string
  count: number
}

export interface FailureRecord {
  node: string
  error: string
  retry_count: number
}

export interface RecommendedAction {
  priority: string
  action: string
  owner: string
}

export interface SharedState {
  goal: string
  scope: Scope
  evidence: {
    normalized_logs: NormalizedLog[]
    anomalies: Anomaly[]
    clusters: Cluster[]
    stack_traces: string[]
  }
  metrics: {
    error_rate: number | null
    latency_p95: number | null
    rps: number | null
  }
  assessment: {
    risk_score: number | null
    confidence: ConfidenceLevel
    rationale: string[]
  }
  decisions: {
    agents_run: string[]
    skipped_agents: string[]
    assumptions: string[]
    failures: FailureRecord[]
    timeouts: string[]
  }
  final: {
    executive_summary: string | null
    recommended_actions: RecommendedAction[] | null
    verification_steps: string[] | null
    additional_data_needed: string[] | null
  }
}

export interface AnalyzeResponse {
  result: SharedState
}

export interface HealthResponse {
  status: string
  model: string
  stub_mode: string
}

export type ExecutionStatus = 'idle' | 'running' | 'completed' | 'failed'

export interface AgentStepStatus {
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
}
