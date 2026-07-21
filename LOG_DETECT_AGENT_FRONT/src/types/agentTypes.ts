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
  include_time_windows?: boolean
  stream_id?: string
}

export interface FingerprintRecommendationRequest {
  service_name: string
  fingerprint: string
  analysis_date?: string
  stream_id?: string
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
  service_name?: string
  category?: string
  sub_category?: string
  cause: string
  recommendation: string
  confidence?: string
}

export interface PatternClusterPartialRefreshResponse {
  affected_fingerprints: string[]
  updated_clusters: Cluster[]
  missing_fingerprints: string[]
}

export interface KnownPatternSaveResponse {
  status: string
  id: number
  fingerprint: string
  partial_refresh?: PatternClusterPartialRefreshResponse
}

export interface FingerprintManualMergeRequest {
  service_name: string
  analysis_date?: string
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
  partial_refresh?: PatternClusterPartialRefreshResponse
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
  llm_reason?: string
  reason_source?: string
  reason_model?: string
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
  partial_refresh?: PatternClusterPartialRefreshResponse
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

export interface SkillActivityStreamItem {
  id: string
  at: string
  execution_id?: string
  skill: string
  agent?: string
  status: string
  action: string
  detail?: string
  reasoning_kind?: AgentReasoningEvent['kind']
  source: 'local-stage' | 'sse' | 'backend-result' | 'fallback' | 'user-action'
}

export interface AgentReasoningEvent {
  event_id: string
  request_id: string
  kind: 'planning' | 'tool_call' | 'self_correction'
  agent_name: string
  status: 'planned' | 'running' | 'completed' | 'failed'
  title: string
  detail: string
  metadata: Record<string, unknown>
}

// --- Agent Process Observability -------------------------------------------
// AgentTraceEvent is an additive, richer contract than AgentReasoningEvent. It
// captures the full process (planning, routing, agent lifecycle, skills, tool
// observations, validation, self-correction, retrieval, persistence) in a
// redaction-safe form. Backend emits these on the `trace` SSE channel and in
// evidence.agent_trace_events. AgentReasoningEvent is preserved unchanged for
// the existing summary activity stream.

export type TraceKind =
  | 'request'
  | 'planning'
  | 'routing'
  | 'agent'
  | 'skill'
  | 'tool_call'
  | 'observation'
  | 'validation'
  | 'retrieval'
  | 'persistence'
  | 'llm'
  | 'self_correction'
  | 'quality'
  | 'fallback'
  | 'sse'

export type TraceStatus =
  | 'planned'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'

export type TraceLayer =
  | 'client'
  | 'api'
  | 'orchestration'
  | 'agent'
  | 'skill'
  | 'reasoning'
  | 'data_access'
  | 'retrieval'
  | 'llm'
  | 'persistence'

export interface TraceInputSummary {
  field_names?: string[]
  field_count?: number
}

export interface TraceOutputSummary {
  type?: string
  count?: number
  field_count?: number
  length?: number
}

export interface TraceError {
  type: string
  summary: string
}

export interface AgentTraceEvent {
  event_id: string
  request_id: string
  trace_id: string
  span_id: string
  parent_span_id: string | null
  sequence: number
  timestamp: string
  duration_ms: number | null
  layer: TraceLayer
  component: string
  agent_name: string
  kind: TraceKind
  event_type: string
  status: TraceStatus
  title: string
  summary: string
  input_summary: TraceInputSummary | null
  output_summary: TraceOutputSummary | null
  decision_summary: string | null
  evidence_refs: string[]
  attempt: number | null
  max_attempts: number | null
  error: TraceError | null
  fallback_used: boolean
  metadata: Record<string, unknown>
}

export type ObservabilityRunStatus =
  | 'running'
  | 'completed'
  | 'degraded'
  | 'failed'

export type ObservabilityConnectionStatus =
  | 'idle'
  | 'connected'
  | 'reconnecting'
  | 'fallback'
  | 'completed'

export type ObservabilityOperation = 'analysis' | 'recommendation'

export interface ObservabilityRun {
  request_id: string
  stream_id: string
  service_name: string
  analysis_date: string
  operation: ObservabilityOperation
  fingerprint?: string
  status: ObservabilityRunStatus
  connection: ObservabilityConnectionStatus
  started_at: string
  ended_at: string | null
  events: AgentTraceEvent[]
}

export interface PatternOpsSkill {
  skill_id: string
  name: string
  category: string
  lifecycle: string
  priority: number
  graph?: Record<string, unknown>
  precondition?: Record<string, unknown>
  operation?: Record<string, unknown>
  artifact?: Record<string, unknown>
  validators?: Array<Record<string, unknown>>
}

export interface PatternOpsSkillEdge {
  edge_id: string
  from_skill_id: string
  to_skill_id: string
  edge_type: string
  weight: number
  reason?: string
}

export interface PatternOpsSkillExecution {
  execution_id: string
  request_id: string
  agent_name: string
  scope: string
  skill_id: string
  status: 'success' | 'failed' | 'selected' | 'planned' | string
  score: number
  reason: string
  input_refs?: string[]
  output_refs?: string[]
}

export interface PatternOpsPreconditionDecision {
  skill_id: string
  passed: boolean
  satisfied: string[]
  missing: string[]
  reason: string
}

export interface PatternOpsEdgeDecision {
  edge_id?: string
  from_skill_id: string
  to_skill_id: string
  edge_type: string
  action: string
  reason: string
}

export interface PatternOpsValidatorResult {
  skill_id: string
  validator_type: string
  passed: boolean
  message: string
}

export interface PatternOpsSkillPlanItem {
  skill_id: string
  name: string
  category: string
  score: number
  reasons: string[]
  precondition?: Record<string, unknown>
  precondition_eval?: Record<string, unknown>
  graph?: Record<string, unknown>
  operation?: Record<string, unknown>
  artifact?: Record<string, unknown>
  validators?: Array<Record<string, unknown>>
}

export interface PatternOpsSkillScopedPlan {
  agent_name?: string
  scope?: string
  selected_skills?: PatternOpsSkillPlanItem[]
  skipped_skills?: PatternOpsSkillPlanItem[]
  skill_edges?: PatternOpsSkillEdge[]
  precondition_decisions?: PatternOpsPreconditionDecision[]
  edge_decisions?: PatternOpsEdgeDecision[]
  excluded_skills?: string[]
}

export interface PatternOpsSkillPlan {
  scope?: string
  selected_skills?: PatternOpsSkillPlanItem[]
  skipped_skills?: PatternOpsSkillPlanItem[]
  skill_edges?: PatternOpsSkillEdge[]
  precondition_decisions?: PatternOpsPreconditionDecision[]
  edge_decisions?: PatternOpsEdgeDecision[]
  excluded_skills?: string[]
  global_plan?: PatternOpsSkillScopedPlan
  scoped_plans?: Record<string, PatternOpsSkillScopedPlan>
}

export interface PatternOpsContract {
  pattern_id: string
  name: string
  category: string
  sub_category: string
  lifecycle: string
  confidence: string
  precondition?: Record<string, unknown>
  operation?: Record<string, unknown>
  artifact?: Record<string, unknown>
  validators?: Array<Record<string, unknown>>
  failure_modes?: string[]
  source?: string
}

export interface PatternOpsSkillsResponse {
  skills: PatternOpsSkill[]
  edges: PatternOpsSkillEdge[]
}

export interface PatternOpsContractsResponse {
  contracts: PatternOpsContract[]
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

export interface AcceptedNormalPatternRequest {
  fingerprint: string
  service_name?: string
  anomaly_type?: string
  reason: string
  approved_by?: string
  scope?: string
  max_allowed_multiplier?: number
  max_allowed_count?: number | null
  expires_at?: string
}

export interface AcceptedNormalPatternItem {
  id: number
  fingerprint: string
  service_name: string
  log_level: string
  normalized_message: string
  anomaly_type: string
  accepted_count: number
  accepted_baseline: number
  max_allowed_count: number | null
  max_allowed_multiplier: number
  scope: string
  reason: string
  approved_by: string
  status: string
  expires_at: string
  created_at: string
  updated_at: string
  message: string
  current_count: number | null
}

export interface AcceptedNormalPatternResponse {
  patterns: AcceptedNormalPatternItem[]
}

export interface AcceptedNormalPatternActionResponse {
  status: string
  id: number
  fingerprint?: string
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

export interface Trajectory {
  trajectory_id: string
  service_name: string
  bucket_size: string
  window_length: number
  start_bucket: string
  end_bucket: string
  vector_ids: string[]
  top_fingerprints: Array<{ fingerprint: string; count: number }>
  features: Record<string, number | string>
  flat_vector: number[]
  label: string
  max_risk_score: number
  anomaly_count: number
  total_events: number
}

export interface TrajectoryCluster {
  cluster_id: string
  service_name: string
  bucket_size: string
  algorithm: string
  representative_trajectory_id: string
  member_trajectory_ids: string[]
  top_fingerprints: Array<{ fingerprint: string; count: number }>
  label: string
  member_count: number
  max_risk_score: number
  anomaly_count: number
  avg_distance: number
}

export interface NearestTrajectoryPattern {
  trajectory_id: string
  cluster_id: string
  label: string
  similarity: number
  distance: number
  representative_trajectory_id: string
  top_fingerprints: Array<{ fingerprint: string; count: number }>
}

// --- RecFM Preview (additive, UI-only) ------------------------------------
// These types describe the RecFM Preview panel. RecFM Preview is a concept
// preview only: there is no trained model and no production inference. All
// derived values are computed on the frontend from Observed /analyze evidence.

export type RecFMDataClass = 'observed' | 'derived' | 'simulation' | 'model_output'

export type RecFMReadinessLevel = 'ready' | 'partial' | 'insufficient'

export interface RecFMDataAvailability {
  bucketSize: string
  requiredBucket: string
  availableBuckets: string[]
  eventWindowCount: number
  stateVectorCount: number
  trajectoryCount: number
  trajectoryClusterCount: number
}

export interface RecFMReadiness {
  level: RecFMReadinessLevel
  requiredBucket: string
  availableBuckets: string[]
  eventWindowCount: number
  stateVectorCount: number
  trajectoryCount: number
  trajectoryClusterCount: number
  featureSchemaVersion: string
  stateVectorDimension: number
  trajectoryWindowLength: number
  observedDurationMinutes: number
  availableServices: string[]
  vectorsWithIncidentIdRatio: number
  labelDistribution: Record<string, number>
  composableTrajectoryCount: number
  targetCandidateCount: number
  missingWindowCount: number
  messages: string[]
}

export interface RecFMStateStep {
  index: number
  symbol: string
  bucketStart: string
  timeLabel: string
  label: string
  totalEvents: number
  errorRatio: number
  warnRatio: number
  anomalyCount: number
  maxRisk: number
  topFingerprint: string
  dataClass: RecFMDataClass
}

export interface RecFMHorizonPreview {
  windows: number
  horizonMinutes: number
  inputWindows: string
  targetSymbols: string[]
  requiredInputWindows: number
  historicalTargetsAvailable: boolean
  trainingSampleComposable: boolean
  status: string
  missingRequirement: string
}

export interface RecFMFlowPoint {
  t: number
  totalEvents: number
  errorRatio: number
  anomalyCount: number
  maxRisk: number
  dataClass: RecFMDataClass
}

export interface Cluster {
  cluster: string
  service_name?: string
  count: number
  lifetime_count?: number
  count_scope?: {
    type: 'analysis_date'
    date: string
  }
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
  accepted_normal?: boolean
  accepted_normal_id?: number | string
  accepted_normal_reason?: string
  accepted_normal_status?: string
}

export interface PatternClusterMember {
  fingerprint: string
  role: string
  pattern_similarity: number
  semantic_similarity: number
  hybrid_score: number
  match_type: string
  occurrence_count: number
}

export interface PatternClusterLink {
  source_cluster_id: string
  target_cluster_id: string
  pattern_similarity: number
  semantic_similarity: number
  hybrid_score: number
  link_type: string
}

export interface PatternCluster {
  cluster_id: string
  service_name: string
  log_level: string
  canonical_fingerprint: string
  representative_template: string
  representative_message: string
  algorithm: string
  member_count: number
  total_occurrence_count: number
  avg_pattern_similarity: number
  min_pattern_similarity: number
  avg_semantic_similarity: number
  max_semantic_similarity: number
  known_status: string
  status: string
  members: PatternClusterMember[]
  links: PatternClusterLink[]
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
  exception_excluded_logs?: number
  accepted_normal_count?: number
  accepted_normal_breach_count?: number
  pattern_clusters?: number
  risk_score: number
  risk_level: string
  detection_status: string
}

export interface FailureRecord {
  node: string
  error: string
  retry_count: number
  skill_id?: string
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
    pattern_clusters?: PatternCluster[]
    stack_traces: string[]
    incident_candidates?: Array<Record<string, unknown>>
    new_pattern_candidates?: Array<Record<string, unknown>>
    duplicate_pattern_candidates?: DuplicatePatternCandidate[]
    pattern_ops_matches?: Array<Record<string, unknown>>
    pattern_ops_contracts?: PatternOpsContract[]
    pattern_ops_skill_graphs?: PatternOpsSkill[]
    pattern_ops_skill_plan?: PatternOpsSkillPlan
    pattern_ops_skill_executions?: PatternOpsSkillExecution[]
    pattern_ops_validator_results?: PatternOpsValidatorResult[]
    agent_reasoning_events?: AgentReasoningEvent[]
    agent_trace_events?: AgentTraceEvent[]
    fingerprint_merge_groups?: FingerprintMergeGroup[]
    event_time_windows?: EventTimeWindow[]
    system_state_vectors?: SystemStateVector[]
    trajectories?: Trajectory[]
    trajectory_clusters?: TrajectoryCluster[]
    nearest_trajectory_patterns?: NearestTrajectoryPattern[]
    // Additive RecFM Preview evidence (10-minute bucket only).
    event_time_windows_10min?: EventTimeWindow[]
    system_state_vectors_10min?: SystemStateVector[]
    trajectories_10min?: Trajectory[]
    trajectory_clusters_10min?: TrajectoryCluster[]
    recfm_bucket_size?: string
    recfm_trajectory_window_length?: number
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
      trajectories?: Trajectory[]
      trajectory_clusters?: TrajectoryCluster[]
      nearest_trajectory_patterns?: NearestTrajectoryPattern[]
      event_time_windows_10min?: EventTimeWindow[]
      system_state_vectors_10min?: SystemStateVector[]
      trajectories_10min?: Trajectory[]
      trajectory_clusters_10min?: TrajectoryCluster[]
      pattern_ops_skill_plan?: PatternOpsSkillPlan
      pattern_ops_skill_executions?: PatternOpsSkillExecution[]
      pattern_ops_validator_results?: PatternOpsValidatorResult[]
      agent_reasoning_events?: AgentReasoningEvent[]
      agent_trace_events?: AgentTraceEvent[]
      pattern_ops_contracts?: PatternOpsContract[]
      pattern_ops_matches?: Array<Record<string, unknown>>
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
