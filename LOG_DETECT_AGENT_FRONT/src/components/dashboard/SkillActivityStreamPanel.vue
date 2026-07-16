<template>
  <section class="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
    <div class="mb-3">
      <div class="flex items-center justify-between">
        <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Agent 추론 · 스킬 활동 스트림
        </p>
        <RouterLink
          to="/agent-observability"
          class="text-[11px] font-medium text-blue-600 hover:text-blue-700"
        >
          상세 추론 로그 보기 →
        </RouterLink>
      </div>
      <div class="mt-2 rounded border border-blue-100 bg-blue-50 p-2">
        <div class="flex items-center justify-between gap-2">
          <p class="text-sm font-semibold text-slate-800">
            {{ current?.skill ?? '대기중' }}
          </p>
          <span
            class="shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold uppercase"
            :class="statusClass(current?.status ?? executionStatus)"
          >
            {{ statusLabel(current?.status ?? executionStatus) }}
          </span>
        </div>
        <p class="mt-1 text-[11px] leading-4 text-slate-600">
          {{ current ? actionLabel(current.action) : '아직 실행 중인 백엔드 스킬이 없습니다.' }}
        </p>
      </div>
    </div>

    <div
      v-if="items.length === 0"
      class="py-6 text-center text-xs text-slate-400"
    >
      실행 stream이 아직 없습니다.
    </div>
    <ol v-else class="max-h-[70vh] space-y-2 overflow-y-auto pr-1">
      <li
        v-for="item in items"
        :key="item.id"
        class="rounded border border-slate-100 bg-slate-50 p-2 text-xs"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate font-semibold text-slate-700">
              {{ item.skill }}
            </p>
            <span
              v-if="item.reasoning_kind"
              class="mt-1 inline-flex rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase"
              :class="reasoningClass(item.reasoning_kind)"
            >
              {{ reasoningLabel(item.reasoning_kind) }}
            </span>
            <p v-if="item.agent" class="mt-0.5 text-[11px] text-slate-400">
              {{ agentLabel(item.agent) }}
            </p>
          </div>
          <span
            class="shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold uppercase"
            :class="statusClass(item.status)"
          >
            {{ statusLabel(item.status) }}
          </span>
        </div>
        <p class="mt-1 text-[11px] leading-4 text-slate-600">
          {{ actionLabel(item.action) }}
        </p>
        <p
          v-if="item.detail"
          class="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-400"
        >
          {{ detailLabel(item.detail) }}
        </p>
        <div class="mt-2 flex items-center justify-between text-[10px] text-slate-400">
          <span>{{ sourceLabel(item.source) }}</span>
          <time>{{ formatTime(item.at) }}</time>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import type { SkillActivityStreamItem } from '@/types/agentTypes'

defineProps<{
  items: SkillActivityStreamItem[]
  current: SkillActivityStreamItem | null
  executionStatus: string
}>()

const skillLabels: Record<string, string> = {
  'Log Collection Skill': '로그 수집 스킬',
  'Log Normalization Skill': '로그 정규화 스킬',
  'Pattern Fingerprint Skill': '패턴 Fingerprint 스킬',
  'Known Pattern Match Skill': 'Known 패턴 매칭 스킬',
  'Duplicate Pattern Detection Skill': '중복 패턴 탐지 스킬',
  'Fingerprint Merge Skill': 'Fingerprint 병합 스킬',
  'Anomaly Detection Skill': '이상 탐지 스킬',
  'Knowledge Card Retrieval Skill': 'Knowledge Card 조회 스킬',
  'Chroma Similar Pattern Retrieval Skill': 'Chroma 유사 패턴 조회 스킬',
  'Recommendation Generation Skill': '추천 생성 스킬',
  'Recommendation Quality Gate Skill': '추천 품질 검증 스킬',
  'Exception Suppression Skill': '예외 억제 스킬',
  'Pattern Rule Suggestion Skill': '패턴 규칙 제안 스킬',
  'Resolution Capture Skill': '해결 내역 캡처 스킬',
  log_collection: '로그 수집 스킬',
  log_normalization: '로그 정규화 스킬',
  pattern_fingerprint: '패턴 Fingerprint 스킬',
  known_pattern_match: 'Known 패턴 매칭 스킬',
  duplicate_pattern_detection: '중복 패턴 탐지 스킬',
  fingerprint_merge: 'Fingerprint 병합 스킬',
  anomaly_detection: '이상 탐지 스킬',
  knowledge_card_retrieval: 'Knowledge Card 조회 스킬',
  chroma_similar_pattern_retrieval: 'Chroma 유사 패턴 조회 스킬',
  recommendation_generation: '추천 생성 스킬',
  recommendation_quality_gate: '추천 품질 검증 스킬',
  exception_suppression: '예외 억제 스킬',
  pattern_rule_suggestion: '패턴 규칙 제안 스킬',
  resolution_capture: '해결 내역 캡처 스킬',
  Completed: '완료'
}

const agentLabels: Record<string, string> = {
  Dashboard: '대시보드',
  OrchestratorAgent: '오케스트레이터 에이전트',
  LogCollectorAgent: '로그 수집 에이전트',
  LogAnalysisAgent: '로그 분석 에이전트',
  KnowledgeBaseRAGAgent: 'Knowledge Base RAG 에이전트',
  AnomalyDetectionAgent: '이상 탐지 에이전트',
  RecommendationAgent: '추천 에이전트'
}

const statusLabels: Record<string, string> = {
  idle: '대기',
  running: '실행 중',
  started: '시작됨',
  completed: '완료',
  success: '성공',
  failed: '실패',
  error: '오류',
  selected: '선택됨',
  planned: '계획됨',
  pending: '대기',
  skipped: '건너뜀'
}

const reasoningLabels: Record<
  NonNullable<SkillActivityStreamItem['reasoning_kind']>,
  string
> = {
  planning: 'Planning',
  tool_call: 'Tool Call',
  self_correction: 'Self-Correction'
}

const sourceLabels: Record<SkillActivityStreamItem['source'], string> = {
  'local-stage': '로컬 단계',
  sse: '실시간 이벤트',
  'backend-result': '백엔드 결과',
  fallback: '대체 처리',
  'user-action': '사용자 요청'
}

const scopeLabels: Record<string, string> = {
  global: '전체',
  ingestion: '수집',
  normalization: '정규화',
  fingerprint: 'Fingerprint',
  matching: '패턴 매칭',
  maintenance: '유지보수',
  detection: '탐지',
  retrieval: '조회',
  recommendation: '추천',
  guard: '가드',
  knowledge_capture: '지식 캡처',
  log_analysis: '로그 분석',
  anomaly_detection: '이상 탐지'
}

const detailLabels: Record<string, string> = {
  entrypoint: '시작점으로 선택됨',
  logs_available: '분석 가능한 로그가 있음',
  normalized_logs_available: '정규화된 로그가 있음',
  fingerprint_or_template_available: 'Fingerprint 또는 템플릿이 있음',
  duplicate_candidates_available: '중복 후보가 있음',
  approved_duplicate_candidate_available: '승인된 중복 후보가 있음',
  fingerprints_or_logs_available: 'Fingerprint 또는 로그가 있음',
  known_pattern_or_incident_hint_available: 'Known 패턴 또는 장애 힌트가 있음',
  pattern_context_available: '패턴 컨텍스트가 있음',
  analysis_evidence_available: '분석 근거가 있음',
  recommendation_candidate_available: '추천 후보가 있음',
  suppressed_logs_available: '억제된 로그가 있음',
  new_pattern_candidates_available: '신규 패턴 후보가 있음',
  final_answer_available_for_approval: '승인 가능한 최종 답변이 있음',
  precondition_passed: '실행 조건 충족'
}

function skillLabel(value: string): string {
  return skillLabels[value] ?? value
}

function agentLabel(value: string): string {
  return agentLabels[value] ?? value
}

function statusLabel(value: string): string {
  return statusLabels[value] ?? value
}

function reasoningLabel(
  value: NonNullable<SkillActivityStreamItem['reasoning_kind']>
): string {
  return reasoningLabels[value]
}

function reasoningClass(
  value: NonNullable<SkillActivityStreamItem['reasoning_kind']>
): string {
  if (value === 'planning') return 'bg-violet-100 text-violet-700'
  if (value === 'tool_call') return 'bg-cyan-100 text-cyan-700'
  return 'bg-fuchsia-100 text-fuchsia-700'
}

function sourceLabel(value: SkillActivityStreamItem['source']): string {
  return sourceLabels[value] ?? value
}

function actionLabel(value: string): string {
  const skillActionMatch = value.match(/^(.+) skill (.+)$/)
  if (skillActionMatch) {
    return `${scopeLabels[skillActionMatch[1]] ?? skillActionMatch[1]} 스킬 ${statusLabel(skillActionMatch[2])}`
  }
  return value
    .replace(/backend/g, '백엔드')
    .replace(/Backend/g, '백엔드')
    .replace(/SSE stream/g, 'SSE 스트림')
    .replace(/Recommendation update/g, '추천 업데이트')
}

function detailLabel(value: string): string {
  return value
    .split(', ')
    .map((part) => {
      if (detailLabels[part]) return detailLabels[part]
      const missing = part.match(/^precondition_missing:(.+)$/)
      if (missing) return `실행 조건 미충족: ${missing[1]}`
      const dependency = part.match(/^dependency_(for|after):(.+)$/)
      if (dependency) return `의존 관계로 선택됨: ${skillLabel(dependency[2])}`
      return skillLabel(part)
    })
    .join(', ')
}

function statusClass(status: string): string {
  if (status === 'completed' || status === 'success') {
    return 'bg-emerald-100 text-emerald-700'
  }
  if (status === 'running' || status === 'started' || status === 'selected') {
    return 'bg-blue-100 text-blue-700'
  }
  if (status === 'planned' || status === 'pending') {
    return 'bg-amber-100 text-amber-700'
  }
  if (status === 'failed' || status === 'error') {
    return 'bg-red-100 text-red-700'
  }
  if (status === 'skipped') return 'bg-slate-200 text-slate-600'
  return 'bg-slate-100 text-slate-600'
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}
</script>
