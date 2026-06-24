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
  service_name: string
  goal?: string
  scope?: Scope
  save_to_chromadb?: boolean
}

export interface FingerprintRecommendationRequest {
  service_name: string
  fingerprint: string
}


export interface RecommendationSaveRequest {
  request_id?: string
  service_name: string
  goal?: string
  executive_summary?: string
  recommendation: string
  recommended_actions?: RecommendedAction[]
  verification_steps?: string[]
  evidence_bundle?: Record<string, unknown>
  risk_score?: number | null
  confidence?: string | null
}

export interface RecommendationSaveResponse {
  status: string
  id: number
}

export interface ApprovalRequest {
  fingerprint: string
  cause: string
  recommendation: string
  resolution_method?: string
  action?: string
  confidence?: string
}

export interface ApprovalResponse {
  result: string
  card_id: string
}

export interface ExceptionRegisterRequest {
  fingerprint: string
  reason: string
}

export interface ExceptionRegisterResponse {
  status: string
  fingerprint: string
}

export interface RecommendationDeleteResponse {
  status: string
  id: number
}

export interface KnowledgeCardItem {
  card_id: string
  fingerprint: string
  cause: string
  recommendation: string
  action: string
  confidence: string
  resolution_method?: string
  created_at: string
  message?: string
  log_level?: string
  service_name?: string
  title?: string
  summary?: string
  symptoms?: string[]
  evidence_text?: string
  root_cause?: string
  remediation_steps?: string[]
  verification_steps?: string[]
  prevention_steps?: string[]
  metadata?: Record<string, unknown>
  rag_document?: string
  embedding_status?: string
}

export interface KnowledgeCardListResponse {
  knowledge_cards: KnowledgeCardItem[]
}

export interface ExceptionRegistryItem {
  fingerprint: string
  reason: string
  created_at: string
  message?: string
  log_level?: string
  service_name?: string
}

export interface ExceptionRegistryResponse {
  exceptions: ExceptionRegistryItem[]
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
  message?: string
  log_level?: string
  semantic_similarity?: number
  similar_clusters?: Array<Record<string, unknown>>
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
  reason?: string
  target?: string
  expected_effect?: string
  risk?: string
  evidence?: string[]
}

export interface SharedState {
  request_id: string
  goal: string
  scope: Scope
  evidence: {
    normalized_logs: NormalizedLog[]
    anomalies: Anomaly[]
    clusters: Cluster[]
    stack_traces: string[]
    incident_candidates?: Array<Record<string, unknown>>
    new_pattern_candidates?: Array<Record<string, unknown>>
  }
  metrics: {
    error_rate: number | null
    latency_p95: number | null
    rps: number | null
    anomaly_score?: number | null
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
  rag?: {
    related_knowledge?: string[]
    saved_to_chromadb?: boolean
  }
  final: {
    executive_summary: string | null
    recommended_actions: RecommendedAction[] | null
    verification_steps: string[] | null
    additional_data_needed: string[] | null
    generated_answer: string | null
    saved_recommendation_id?: number | null
    evidence_bundle?: {
      summary?: {
        total_logs: number
        total_fingerprints: number
        known_patterns: number
        new_patterns: number
        anomalies_detected: number
        exception_registered_count: number
        risk_score: number
        risk_level: string
        detection_status: string
      }
      recommendation?: {
        cause: string
        recommendation: string
        confidence: string
      }
    } | null
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

export interface ServiceListResponse {
  services: string[]
}

export interface RecommendationHistoryItem {
  id: number
  request_id: string
  service_name: string
  goal: string
  executive_summary: string
  recommendation: string
  recommended_actions: RecommendedAction[]
  verification_steps: string[]
  evidence_bundle: Record<string, unknown>
  risk_score: number | null
  confidence: string | null
  created_at: string
}

export interface RecommendationHistoryResponse {
  recommendations: RecommendationHistoryItem[]
}

export type ExecutionStatus = 'idle' | 'running' | 'completed' | 'failed'

export interface AgentStepStatus {
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
}
