import axios from 'axios'
import type { AnalyzeRequest, AnalyzeResponse, HealthResponse } from '@/types/agentTypes'

const apiClient = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000',
  timeout: 30000
})

export const agentApi = {
  analyze(payload: AnalyzeRequest) {
    return apiClient.post<AnalyzeResponse>('/analyze', payload)
  },
  health() {
    return apiClient.get<HealthResponse>('/health')
  }
}
