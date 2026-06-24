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
  KnowledgeCardListResponse,
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
  knowledgeCards(params?: { fingerprint?: string; limit?: number }) {
    return apiClient.get<KnowledgeCardListResponse>('/knowledge-cards', {
      params
    })
  },
  exceptions(params?: { fingerprint?: string; limit?: number }) {
    return apiClient.get<ExceptionRegistryResponse>('/exceptions', { params })
  }
}
