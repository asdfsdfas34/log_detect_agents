import axios from 'axios'
import type {
  ApprovalRequest,
  ApprovalResponse,
  AnalyzeRequest,
  AnalyzeResponse,
  DuplicatePatternCandidateActionResponse,
  DuplicatePatternCandidatesResponse,
  ExceptionRegisterRequest,
  ExceptionRegisterResponse,
  ExceptionRegistryResponse,
  FingerprintRecommendationRequest,
  FingerprintManualMergeRequest,
  FingerprintManualMergeResponse,
  HealthResponse,
  KnownPatternSaveRequest,
  KnownPatternSaveResponse,
  KnowledgeCardListResponse,
  PatternRuleProposal,
  PatternRuleSaveRequest,
  PatternRuleSaveResponse,
  PatternRuleSuggestRequest,
  PatternOpsContractsResponse,
  PatternOpsSkillsResponse,
  RecommendationDeleteResponse,
  RecommendationHistoryResponse,
  RecommendationSaveRequest,
  RecommendationSaveResponse,
  ServiceListResponse,
  SimilarPatternClustersResponse
} from '@/types/agentTypes'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  timeout: 300000
})

export const agentApi = {
  analyze(payload: AnalyzeRequest) {
    return apiClient.post<AnalyzeResponse>('/analyze', payload)
  },
  recommendationForFingerprint(payload: FingerprintRecommendationRequest) {
    return apiClient.post<AnalyzeResponse>(
      '/recommendations/fingerprint',
      payload
    )
  },
  health() {
    return apiClient.get<HealthResponse>('/health')
  },
  services() {
    return apiClient.get<ServiceListResponse>('/services')
  },
  recommendations(params?: { service_name?: string; limit?: number }) {
    return apiClient.get<RecommendationHistoryResponse>('/recommendations', {
      params
    })
  },
  saveRecommendation(payload: RecommendationSaveRequest) {
    return apiClient.post<RecommendationSaveResponse>(
      '/recommendations/save',
      payload
    )
  },
  deleteRecommendation(recommendationId: number) {
    return apiClient.delete<RecommendationDeleteResponse>(
      `/recommendations/${recommendationId}`
    )
  },
  approveRecommendation(payload: ApprovalRequest) {
    return apiClient.post<ApprovalResponse>('/approvals', payload)
  },
  registerException(payload: ExceptionRegisterRequest) {
    return apiClient.post<ExceptionRegisterResponse>('/exceptions', payload)
  },
  saveKnownPattern(payload: KnownPatternSaveRequest) {
    return apiClient.post<KnownPatternSaveResponse>('/known-patterns', payload)
  },
  manualMergeFingerprints(payload: FingerprintManualMergeRequest) {
    return apiClient.post<FingerprintManualMergeResponse>(
      '/fingerprints/manual-merge',
      payload
    )
  },
  suggestPatternRule(payload: PatternRuleSuggestRequest) {
    return apiClient.post<PatternRuleProposal>('/pattern-rules/suggest', payload)
  },
  savePatternRule(payload: PatternRuleSaveRequest) {
    return apiClient.post<PatternRuleSaveResponse>('/pattern-rules', payload)
  },
  duplicatePatternCandidates(params?: { status?: string; limit?: number }) {
    return apiClient.get<DuplicatePatternCandidatesResponse>(
      '/pattern-duplicates',
      { params }
    )
  },
  similarPatternClusters(
    fingerprint: string,
    params: { service_name: string; limit?: number }
  ) {
    return apiClient.get<SimilarPatternClustersResponse>(
      `/pattern-clusters/${encodeURIComponent(fingerprint)}/similar`,
      { params }
    )
  },
  approveDuplicatePatternCandidate(candidateKey: string) {
    return apiClient.post<DuplicatePatternCandidateActionResponse>(
      `/pattern-duplicates/${candidateKey}/approve`
    )
  },
  rejectDuplicatePatternCandidate(candidateKey: string) {
    return apiClient.post<DuplicatePatternCandidateActionResponse>(
      `/pattern-duplicates/${candidateKey}/reject`
    )
  },
  knowledgeCards(params?: { fingerprint?: string; limit?: number }) {
    return apiClient.get<KnowledgeCardListResponse>('/knowledge-cards', {
      params
    })
  },
  exceptions(params?: { fingerprint?: string; limit?: number }) {
    return apiClient.get<ExceptionRegistryResponse>('/exceptions', { params })
  },
  patternOpsSkills(params?: { limit?: number }) {
    return apiClient.get<PatternOpsSkillsResponse>('/patternops/skills', {
      params
    })
  },
  patternOpsContracts(params?: { limit?: number }) {
    return apiClient.get<PatternOpsContractsResponse>('/patternops/contracts', {
      params
    })
  }
}
