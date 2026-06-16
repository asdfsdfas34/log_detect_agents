import axios from 'axios'
import type { AnalyzeRequest, AnalyzeResponse, FingerprintRecommendationRequest, HealthResponse, RecommendationHistoryResponse, ServiceListResponse } from '@/types/agentTypes'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  timeout: 30000
})

export const agentApi = {
  analyze(payload: AnalyzeRequest) {
    return apiClient.post<AnalyzeResponse>('/analyze', payload)
  },
  recommendationForFingerprint(payload: FingerprintRecommendationRequest) {
    return apiClient.post<AnalyzeResponse>('/recommendations/fingerprint', payload)
  },
  health() {
    return apiClient.get<HealthResponse>('/health')
  },
  services() {
    return apiClient.get<ServiceListResponse>('/services')
  },
  recommendations(params?: { service_name?: string; limit?: number }) {
    return apiClient.get<RecommendationHistoryResponse>('/recommendations', { params })
  }
}
