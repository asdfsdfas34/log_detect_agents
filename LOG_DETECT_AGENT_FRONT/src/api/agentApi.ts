import axios from 'axios'
import type {
  ApprovalRequest,
  ApprovalResponse,
  AnalyzeRequest,
  AnalyzeResponse,
  ExceptionRegisterRequest,
  ExceptionRegisterResponse,
  ExceptionRegistryResponse,
  FingerprintRecommendationRequest,
  HealthResponse,
  KnownPatternSaveRequest,
  KnownPatternSaveResponse,
  KnowledgeCardListResponse,
  LangSmithRunsResponse,
  PatternRuleProposal,
  PatternRuleSaveRequest,
  PatternRuleSaveResponse,
  PatternRuleSuggestRequest,
  RecommendationDeleteResponse,
  RecommendationHistoryResponse,
  RecommendationSaveRequest,
  RecommendationSaveResponse,
  ServiceListResponse
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
  langSmithRuns(params?: { limit?: number }) {
    return apiClient.get<LangSmithRunsResponse>('/langsmith/runs', { params })
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
  suggestPatternRule(payload: PatternRuleSuggestRequest) {
    return apiClient.post<PatternRuleProposal>('/pattern-rules/suggest', payload)
  },
  savePatternRule(payload: PatternRuleSaveRequest) {
    return apiClient.post<PatternRuleSaveResponse>('/pattern-rules', payload)
  },
  knowledgeCards(params?: { fingerprint?: string; limit?: number }) {
    return apiClient.get<KnowledgeCardListResponse>('/knowledge-cards', {
      params
    })
  },
  exceptions(params?: { fingerprint?: string; limit?: number }) {
    return apiClient.get<ExceptionRegistryResponse>('/exceptions', { params })
  }
}
