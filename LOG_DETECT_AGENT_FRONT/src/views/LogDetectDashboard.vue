<template>
  <AppLayout>
    <template #header-right>
      <div class="flex items-center gap-3">
        <button
          class="rounded border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50"
          :disabled="store.loadingServices"
          @click="openServiceLayer"
        >
          서비스선택
        </button>
        <input
          :value="serviceName"
          type="text"
          readonly
          placeholder="선택된 서비스 없음"
          class="w-56 rounded border border-slate-300 bg-slate-50 px-3 py-2 text-sm"
        />
        <div class="text-right text-xs text-slate-600">
          <p>
            Status:
            <span class="font-semibold">{{ store.executionStatus }}</span>
          </p>
          <p>
            Stage: <span class="font-semibold">{{ store.currentStage }}</span>
          </p>
          <p>Last run: {{ store.lastExecutionAt ?? '-' }}</p>
        </div>
        <input
          v-model="analysisDate"
          type="date"
          class="rounded border border-slate-300 bg-white px-3 py-2 text-sm"
          aria-label="Analysis date"
        />
        <button
          class="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          :disabled="store.loading || !serviceName.trim() || !analysisDate"
          @click="handleRunAnalysis"
        >
          Re-run analysis
        </button>
      </div>
    </template>

    <section class="space-y-4">
      <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h2
          class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500"
        >
          Detection Summary
        </h2>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <OverviewCard label="Total Logs" :value="store.overview.totalLogs" />
          <OverviewCard
            label="Total Fingerprints"
            :value="store.overview.totalFingerprints"
          />
          <OverviewCard
            label="Known Patterns"
            :value="store.overview.knownPatterns"
          />
          <OverviewCard
            label="New Patterns"
            :value="store.overview.newPatterns"
          />
          <OverviewCard
            label="Anomalies Detected"
            :value="store.overview.anomaliesDetected"
          />
          <OverviewCard
            label="Exception Registered Count"
            :value="store.overview.exceptionRegisteredCount"
          />
          <OverviewCard
            label="Exception Excluded"
            :value="store.overview.exceptionExcludedLogs"
          />
        </div>
      </div>

      <AnomalyTimelineChart
        v-if="store.state"
        :anomalies="store.state.evidence.anomalies"
        :daily-counts="store.state.evidence.anomaly_daily_counts"
        :logs="store.state.evidence.normalized_logs"
      />
    </section>

    <LoadingSpinner
      v-if="store.loading"
      label="Running multi-agent analysis"
      :stage-log="store.currentExecutionLog"
    />
    <ErrorState v-else-if="store.error" :message="store.error" />

    <template v-if="store.state">
      <DuplicatePatternCandidatePanel
        :candidates="store.duplicatePatternCandidates"
        :loading="store.loadingDuplicatePatternCandidates"
        :busy-key="duplicateCandidateBusyKey"
        @refresh="store.fetchDuplicatePatternCandidates"
        @approve="handleApproveDuplicateCandidate"
        @reject="handleRejectDuplicateCandidate"
      />
      <TrajectoryModelingPanel
        :merge-groups="trajectoryMergeGroups"
        :event-windows="trajectoryEventWindows"
        :state-vectors="trajectoryStateVectors"
      />
      <PatternClusterTable
        ref="patternClusterTable"
        :clusters="store.state.evidence.clusters"
        :service-name="serviceName"
        @save-known-pattern="handleSaveKnownPattern"
        @request-recommendation="handleRequestRecommendation"
        @suggest-pattern-rule="handleSuggestPatternRule"
        @manual-merge-known="handleManualMergeKnown"
      />
      <RecommendationPanel
        :actions="store.state.final.recommended_actions ?? []"
        :verification="store.state.final.verification_steps ?? []"
        :generated-answer="store.state.final.generated_answer"
        :can-moderate="canModerateRecommendation"
        @save-case="handleSaveCase"
        @save-recommendation="handleSaveRecommendation"
        @save-exception="handleSaveException"
      />
    </template>

    <RecommendationHistoryPanel
      :items="store.recommendationHistory"
      :loading="store.loadingRecommendations"
      :knowledge-cards="store.knowledgeCards"
      :loading-knowledge-cards="store.loadingKnowledgeCards"
      :exceptions="store.exceptionRegistry"
      :loading-exceptions="store.loadingExceptions"
      @refresh="handleRefreshRecommendations"
      @fetch-knowledge-cards="handleFetchKnowledgeCards"
      @fetch-exceptions="handleFetchExceptions"
      @delete-recommendation="handleDeleteRecommendation"
    />

    <KnowledgeCardReviewModal
      v-if="knowledgeCardDraft"
      :fingerprint="knowledgeCardDraft.fingerprint"
      :cause="knowledgeCardDraft.cause"
      :recommendation="knowledgeCardDraft.recommendation"
      :resolution-method="knowledgeCardDraft.resolutionMethod"
      :confidence="knowledgeCardDraft.confidence"
      @cancel="knowledgeCardDraft = null"
      @save="handleConfirmKnowledgeCard"
    />

    <aside class="fixed left-4 top-28 z-20 hidden w-56 xl:block">
      <AgentProgressTimeline :steps="store.agentTimeline" compact />
    </aside>

    <aside class="fixed right-4 top-28 z-20 hidden w-80 2xl:block">
      <LangSmithLogPanel
        :runs="store.langSmithRuns"
        :loading="store.loadingLangSmithRuns"
        :status="store.langSmithStatus"
        @refresh="store.fetchLangSmithRuns"
      />
    </aside>

    <EmptyState
      v-if="!store.state && !store.loading"
      message="No analysis result yet. Trigger a run to populate the dashboard."
    />

    <div class="fixed bottom-4 right-4 space-y-2">
      <div
        v-for="toast in store.toasts"
        :key="toast.id"
        class="rounded px-3 py-2 text-sm text-white shadow"
        :class="toast.level === 'error' ? 'bg-red-600' : 'bg-slate-800'"
      >
        {{ toast.message }}
      </div>
    </div>

    <div
      v-if="showServiceLayer"
      class="fixed inset-0 z-40 flex items-center justify-center bg-black/40"
      @click.self="showServiceLayer = false"
    >
      <div class="w-full max-w-md rounded-lg bg-white p-4 shadow-xl">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-base font-semibold text-slate-800">서비스 선택</h3>
          <button
            class="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
            @click="showServiceLayer = false"
          >
            닫기
          </button>
        </div>
        <div
          v-if="store.loadingServices"
          class="py-8 text-center text-sm text-slate-500"
        >
          서비스 목록 로딩중...
        </div>
        <div
          v-else-if="store.serviceOptions.length === 0"
          class="py-8 text-center text-sm text-slate-500"
        >
          선택 가능한 서비스가 없습니다.
        </div>
        <ul v-else class="max-h-72 space-y-2 overflow-y-auto">
          <li v-for="service in store.serviceOptions" :key="service">
            <button
              class="w-full rounded border border-slate-200 px-3 py-2 text-left text-sm hover:bg-slate-50"
              @click="handleSelectService(service)"
            >
              {{ service }}
            </button>
          </li>
        </ul>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import OverviewCard from '@/components/dashboard/OverviewCard.vue'
import DuplicatePatternCandidatePanel from '@/components/dashboard/DuplicatePatternCandidatePanel.vue'
import TrajectoryModelingPanel from '@/components/dashboard/TrajectoryModelingPanel.vue'
import PatternClusterTable from '@/components/dashboard/PatternClusterTable.vue'
import AnomalyTimelineChart from '@/components/dashboard/AnomalyTimelineChart.vue'
import RecommendationPanel from '@/components/dashboard/RecommendationPanel.vue'
import RecommendationHistoryPanel from '@/components/dashboard/RecommendationHistoryPanel.vue'
import KnowledgeCardReviewModal from '@/components/dashboard/KnowledgeCardReviewModal.vue'
import AgentProgressTimeline from '@/components/dashboard/AgentProgressTimeline.vue'
import LangSmithLogPanel from '@/components/dashboard/LangSmithLogPanel.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useLogDetectStore } from '@/stores/logDetectStore'
import type {
  Cluster,
  DuplicatePatternCandidate,
  EventTimeWindow,
  FingerprintMergeGroup,
  SystemStateVector
} from '@/types/agentTypes'

const store = useLogDetectStore()
const serviceName = ref('')
const analysisDate = ref(new Date().toISOString().slice(0, 10))
const showServiceLayer = ref(false)
const duplicateCandidateBusyKey = ref<string | null>(null)
const patternClusterTable = ref<InstanceType<typeof PatternClusterTable> | null>(null)
const knowledgeCardDraft = ref<{
  fingerprint: string
  cause: string
  recommendation: string
  resolutionMethod: string
  confidence: string
} | null>(null)
const canModerateRecommendation = computed(
  () =>
    Boolean(store.state?.final.generated_answer) &&
    Boolean(store.currentRecommendationFingerprint)
)

const evidenceBundle = computed(
  () => store.state?.final.evidence_bundle as Record<string, unknown> | null | undefined
)

const trajectoryMergeGroups = computed(() => {
  const evidenceItems = store.state?.evidence.fingerprint_merge_groups
  if (evidenceItems?.length) return evidenceItems
  return (evidenceBundle.value?.fingerprint_merge_groups ??
    []) as FingerprintMergeGroup[]
})

const trajectoryEventWindows = computed(() => {
  const evidenceItems = store.state?.evidence.event_time_windows
  if (evidenceItems?.length) return evidenceItems
  return (evidenceBundle.value?.event_time_windows ?? []) as EventTimeWindow[]
})

const trajectoryStateVectors = computed(() => {
  const evidenceItems = store.state?.evidence.system_state_vectors
  if (evidenceItems?.length) return evidenceItems
  return (evidenceBundle.value?.system_state_vectors ?? []) as SystemStateVector[]
})

async function openServiceLayer() {
  await store.fetchServices()
  showServiceLayer.value = true
}

function handleSelectService(service: string) {
  serviceName.value = service
  showServiceLayer.value = false
  void store.fetchRecommendations(service)
}

function handleRunAnalysis() {
  const trimmed = serviceName.value.trim()
  if (!trimmed || !analysisDate.value) return
  void store.runAnalysis(trimmed, analysisDate.value)
}

function handleRequestRecommendation(cluster: Cluster) {
  const trimmed = serviceName.value.trim()
  if (!trimmed) return
  const approved = window.confirm(
    `${cluster.cluster} 패턴에 대한 Recommendation을 생성하시겠습니까?`
  )
  if (!approved) return
  void store.runClusterRecommendation(trimmed, cluster.cluster, analysisDate.value)
}

async function handleSaveKnownPattern(cluster: Cluster) {
  const cause = window.prompt(
    `${cluster.cluster} Known Pattern 원인을 입력해주세요.`,
    cluster.message ?? ''
  )
  if (!cause?.trim()) return
  const recommendation = window.prompt(
    `${cluster.cluster} Known Pattern Recommendation을 입력해주세요.`
  )
  if (!recommendation?.trim()) return
  const approved = window.confirm(
    `${cluster.cluster} 패턴을 Known Pattern으로 저장하시겠습니까?`
  )
  if (!approved) return
  const saved = await store.saveKnownPattern(
    cluster.cluster,
    cause.trim(),
    recommendation.trim()
  )
  if (saved) {
    cluster.pattern_status = 'known_exact'
    cluster.match_source = 'known_patterns'
  }
}

async function handleManualMergeKnown(fingerprints: string[]) {
  const trimmed = serviceName.value.trim()
  if (!trimmed || fingerprints.length < 2) return
  const approved = window.confirm(
    `${fingerprints.length}개 fingerprint를 병합하고 Known Pattern으로 등록하시겠습니까?`
  )
  if (!approved) return
  const cause = window.prompt(
    'Known Pattern 원인을 입력해주세요.',
    'Selected fingerprints represent the same parameter conversion failure.'
  )
  if (!cause?.trim()) return
  const recommendation = window.prompt(
    '권고 사항을 입력해주세요.',
    'Normalize variable NUM length values and review the function parameter mapping.'
  )
  if (!recommendation?.trim()) return
  const merged = await store.manualMergeFingerprints({
    service_name: trimmed,
    fingerprints,
    cause,
    recommendation,
    confidence: 'HIGH'
  })
  if (merged) {
    patternClusterTable.value?.clearSelectedFingerprints()
  }
}

async function handleSuggestPatternRule(cluster: Cluster) {
  const message = cluster.message?.trim()
  if (!message) return
  const proposal = await store.suggestPatternRule(cluster.cluster, message)
  if (!proposal) return
  const approved = window.confirm(
    [
      `${cluster.cluster} 패턴 정규화 룰을 저장하시겠습니까?`,
      '',
      `Template: ${proposal.template}`,
      `Regex: ${proposal.match_regex}`,
      '',
      proposal.reason
    ].join('\n')
  )
  if (!approved) return
  await store.savePatternRule(
    proposal.name,
    proposal.match_regex,
    proposal.template
  )
}

async function handleApproveDuplicateCandidate(
  candidate: DuplicatePatternCandidate
) {
  const approved = window.confirm(
    [
      `${candidate.fingerprints.join(', ')} 후보를 하나의 pattern rule로 승인하시겠습니까?`,
      '',
      `Template: ${candidate.suggested_template}`,
      `Regex: ${candidate.suggested_regex}`
    ].join('\n')
  )
  if (!approved) return
  duplicateCandidateBusyKey.value = candidate.candidate_key
  try {
    await store.approveDuplicatePatternCandidate(candidate.candidate_key)
  } finally {
    duplicateCandidateBusyKey.value = null
  }
}

async function handleRejectDuplicateCandidate(
  candidate: DuplicatePatternCandidate
) {
  const approved = window.confirm(
    `${candidate.candidate_key} duplicate 후보를 거절하시겠습니까?`
  )
  if (!approved) return
  duplicateCandidateBusyKey.value = candidate.candidate_key
  try {
    await store.rejectDuplicatePatternCandidate(candidate.candidate_key)
  } finally {
    duplicateCandidateBusyKey.value = null
  }
}

function handleRefreshRecommendations() {
  const trimmed = serviceName.value.trim()
  void store.fetchRecommendations(trimmed || undefined)
}

function handleFetchKnowledgeCards() {
  void store.fetchKnowledgeCards()
}

function handleFetchExceptions() {
  void store.fetchExceptionRegistry()
}

function handleDeleteRecommendation(recommendationId: number) {
  const confirmed = window.confirm(
    `Recommendation #${recommendationId} 항목을 삭제하시겠습니까?`
  )
  if (!confirmed) return
  void store.deleteSavedRecommendation(recommendationId)
}

function handleSaveCase() {
  const fingerprint = store.currentRecommendationFingerprint
  if (!fingerprint) return
  knowledgeCardDraft.value = {
    fingerprint,
    cause: store.currentRecommendationCause || '-',
    recommendation: store.state?.final.generated_answer ?? '',
    resolutionMethod: '',
    confidence: store.currentRecommendationConfidence || 'MEDIUM'
  }
}

async function handleConfirmKnowledgeCard(draft: {
  cause: string
  recommendation: string
  resolutionMethod: string
  confidence: string
}) {
  const saved = await store.approveCurrentRecommendation(draft)
  if (saved) {
    knowledgeCardDraft.value = null
  }
}

function handleSaveRecommendation() {
  const trimmed = serviceName.value.trim()
  if (!trimmed) return
  const approved = window.confirm('현재 Recommendation을 저장하시겠습니까?')
  if (!approved) return
  void store.saveCurrentRecommendation(trimmed)
}

function handleSaveException() {
  const fingerprint = store.currentRecommendationFingerprint
  if (!fingerprint) return
  const reason = window.prompt(
    `${fingerprint} 예외처리 저장 사유를 입력해주세요.`
  )
  if (!reason?.trim()) return
  void store.registerCurrentException(reason.trim())
}

onMounted(async () => {
  await store.fetchHealth()
  await store.fetchServices()
  await store.fetchRecommendations()
  await store.fetchKnowledgeCards()
  await store.fetchExceptionRegistry()
  await store.fetchDuplicatePatternCandidates()
  await store.fetchLangSmithRuns()
})
</script>
