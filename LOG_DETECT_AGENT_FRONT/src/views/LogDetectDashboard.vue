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
        <button
          class="rounded border px-3 py-2 text-xs"
          :class="
            saveToChromaDb
              ? 'border-emerald-600 bg-emerald-600 text-white'
              : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-50'
          "
          @click="saveToChromaDb = !saveToChromaDb"
        >
          {{ saveToChromaDb ? 'ChromaDB 저장: ON' : 'ChromaDB 저장: OFF' }}
        </button>
        <button
          class="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          :disabled="store.loading || !serviceName.trim()"
          @click="handleRunAnalysis"
        >
          Re-run analysis
        </button>
      </div>
    </template>

    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
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
        </div>
      </div>

      <div
        class="rounded-lg border border-slate-200 bg-white p-4 text-center shadow-sm"
      >
        <h2
          class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500"
        >
          Risk Summary
        </h2>
        <p class="text-sm text-slate-500">Impact Score</p>
        <p class="text-5xl font-bold text-slate-900">
          {{ store.overview.riskScore }}
        </p>
        <p class="mt-1 text-lg font-semibold text-red-600">
          {{ store.overview.riskLevel }}
        </p>
        <p class="mt-4 text-sm text-slate-600">
          Detection Status:
          <span class="font-semibold">{{
            store.overview.detectionStatus
          }}</span>
        </p>
      </div>

      <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h2
          class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500"
        >
          Recommendation Summary
        </h2>
        <dl class="space-y-3 text-sm">
          <div>
            <dt class="font-semibold text-slate-600">Cause</dt>
            <dd>{{ store.recommendationSummary?.cause ?? '-' }}</dd>
          </div>
          <div>
            <dt class="font-semibold text-slate-600">Recommendation</dt>
            <dd>{{ store.recommendationSummary?.recommendation ?? '-' }}</dd>
          </div>
          <div>
            <dt class="font-semibold text-slate-600">Confidence</dt>
            <dd>{{ store.recommendationSummary?.confidence ?? '-' }}</dd>
          </div>
        </dl>
      </div>
    </section>

    <LoadingSpinner v-if="store.loading" label="Running multi-agent analysis" />
    <ErrorState v-else-if="store.error" :message="store.error" />

    <template v-if="store.state">
      <div class="grid gap-6 xl:grid-cols-2">
        <PatternClusterTable
          :clusters="store.state.evidence.clusters"
          @select-cluster="handleSelectCluster"
        />
        <AnomalyTimelineChart
          :anomalies="store.state.evidence.anomalies"
          :logs="store.state.evidence.normalized_logs"
        />
      </div>
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

    <aside class="fixed left-4 top-28 z-20 hidden w-56 xl:block">
      <AgentProgressTimeline :steps="store.agentTimeline" compact />
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
import PatternClusterTable from '@/components/dashboard/PatternClusterTable.vue'
import AnomalyTimelineChart from '@/components/dashboard/AnomalyTimelineChart.vue'
import RecommendationPanel from '@/components/dashboard/RecommendationPanel.vue'
import RecommendationHistoryPanel from '@/components/dashboard/RecommendationHistoryPanel.vue'
import AgentProgressTimeline from '@/components/dashboard/AgentProgressTimeline.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useLogDetectStore } from '@/stores/logDetectStore'
import type { Cluster } from '@/types/agentTypes'

const store = useLogDetectStore()
const serviceName = ref('')
const saveToChromaDb = ref(false)
const showServiceLayer = ref(false)
const canModerateRecommendation = computed(
  () =>
    Boolean(store.state?.final.generated_answer) &&
    Boolean(store.currentRecommendationFingerprint)
)

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
  if (!trimmed) return
  void store.runAnalysis(trimmed, saveToChromaDb.value)
}

function handleSelectCluster(cluster: Cluster) {
  const trimmed = serviceName.value.trim()
  if (!trimmed) return
  void store.runClusterRecommendation(trimmed, cluster.cluster)
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
  const resolutionMethod = window.prompt(
    `${fingerprint} Case를 어떻게 해결했는지 입력해주세요.`
  )
  if (!resolutionMethod?.trim()) return
  const approved = window.confirm(
    `${fingerprint} Case를 Knowledge Card로 저장하시겠습니까?`
  )
  if (!approved) return
  void store.approveCurrentRecommendation(resolutionMethod.trim())
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
})
</script>
