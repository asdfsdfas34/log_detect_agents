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
  analysis_date?: string
  include_similar_clusters?: boolean
}

export interface FingerprintRecommendationRequest {
  service_name: string
  fingerprint: string
  analysis_date?: string
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

export interface KnownPatternSaveRequest {
  fingerprint: string
  category?: string
  sub_category?: string
  cause: string
  recommendation: string
  confidence?: string
}

export interface KnownPatternSaveResponse {
  status: string
  id: number
  fingerprint: string
}

export interface FingerprintManualMergeRequest {
  service_name: string
  fingerprints: string[]
  cause: string
  recommendation: string
  confidence?: string
}

export interface FingerprintManualMergeResponse {
  status: string
  candidate_key?: string
  rule_id?: number
  known_pattern_id?: number
  canonical_fingerprint?: string
  merge?: {
    merged: boolean
    canonical_fingerprint?: string
    merged_fingerprints?: string[]
    occurrence_count?: number
    reason?: string
    chroma?: Record<string, number>
  }
}

export interface PatternRuleSuggestRequest {
  cluster?: string
  message: string
}

export interface PatternRuleProposal {
  name: string
  match_regex: string
  template: string
  confidence: string
  reason: string
  sample_before: string
  sample_after: string
}

export interface PatternRuleSaveRequest {
  name: string
  match_regex: string
  template: string
  enabled?: boolean
  priority?: number
}

export interface PatternRuleSaveResponse {
  status: string
  id: number
}

export interface DuplicatePatternCandidate {
  candidate_key: string
  service_name: string
  log_level: string
  signature: string
  fingerprints: string[]
  fingerprint_details?: Record<
    string,
    {
      fingerprint: string
      service_name?: string
      log_level?: string
      message?: string
      normalized_message?: string
      stacktrace?: string
      occurrence_count?: number
      first_seen?: string
      last_seen?: string
    }
  >
  suggested_regex: string
  suggested_template: string
  confidence: number
  reason: string
  status: string
  created_at?: string
  updated_at?: string
}

export interface DuplicatePatternCandidatesResponse {
  candidates: DuplicatePatternCandidate[]
}

export interface DuplicatePatternCandidateActionResponse {
  status: string
  rule_id?: number
  candidate?: DuplicatePatternCandidate | null
  merge?: {
    merged: boolean
    canonical_fingerprint?: string
    merged_fingerprints?: string[]
    occurrence_count?: number
    reason?: string
    chroma?: Record<string, number>
  }
}

export interface RecommendationDeleteResponse {
  status: string
  id: number
}

export interface LangSmithRunItem {
  id: string
  request_id?: string
  name: string
  run_type?: string
  status: string
  elapsed_ms?: number | null
  error?: string
  start_time?: string
  project_name?: string
  source: string
}

export interface LangSmithRunsResponse {
  enabled: boolean
  project: string
  source: string
  runs: LangSmithRunItem[]
  error?: string | null
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
  timestamp?: string
  system?: string
  severity?: string
  pattern?: string
  message?: string
  anomaly_type?: string
  spike_ratio?: number
  metric?: Record<string, unknown>
}

export interface AnomalyDailyCount {
  service_name: string
  analysis_date: string
  anomaly_count: number
}

export interface FingerprintMergeGroup {
  group_id: string
  candidate_key: string
  canonical_fingerprint: string
  service_name: string
  log_level: string
  representative_template: string
  member_fingerprints: string[]
  avg_similarity: number
  min_similarity: number
  total_occurrence_count: number
  status: string
}

export interface EventTimeWindow {
  window_id: string
  service_name: string
  bucket_start: string
  bucket_size: string
  total_events: number
  error_events: number
  warn_events: number
  info_events: number
  unique_fingerprints: number
  known_fingerprint_count: number
  new_fingerprint_count: number
  anomaly_count: number
  max_risk_score: number
  top_fingerprints: Array<{ fingerprint: string; count: number }>
}

export interface SystemStateVector {
  vector_id: string
  scope_key: string
  service_name: string
  bucket_start: string
  bucket_size: string
  feature_schema_version: string
  features: Record<string, number>
  vector: number[]
  label: string
  incident_id?: string
}

export interface Cluster {
  cluster: string
  count: number
  message?: string
  log_level?: string
  stacktrace?: string
  pattern_status?: string
  match_source?: string
  similar_fingerprint?: string
  similarity_score?: number | null
  semantic_similarity?: number
  similar_clusters?: Array<Record<string, unknown>>
  anomaly_detected?: boolean
  anomaly_type?: string
  anomaly_severity?: string
  anomaly_reason?: string
  anomaly_metric?: Record<string, unknown>
}

export interface SimilarPatternClustersResponse {
  fingerprint: string
  service_name: string
  semantic_similarity: number
  similar_clusters: Array<Record<string, unknown>>
}

export interface ScenarioSummary {
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
    duplicate_pattern_candidates?: DuplicatePatternCandidate[]
    fingerprint_merge_groups?: FingerprintMergeGroup[]
    event_time_windows?: EventTimeWindow[]
    system_state_vectors?: SystemStateVector[]
    anomaly_daily_counts?: AnomalyDailyCount[]
    summary?: ScenarioSummary
    recommendation?: Record<string, unknown>
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
      summary?: ScenarioSummary
      recommendation?: {
        cause: string
        recommendation: string
        confidence: string
      }
      fingerprint_merge_groups?: FingerprintMergeGroup[]
      event_time_windows?: EventTimeWindow[]
      system_state_vectors?: SystemStateVector[]
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
