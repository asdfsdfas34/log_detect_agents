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
          <p>Status: <span class="font-semibold">{{ store.executionStatus }}</span></p>
          <p>Stage: <span class="font-semibold">{{ store.currentStage }}</span></p>
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
        <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Detection Summary</h2>
        <div class="grid grid-cols-2 gap-3 text-sm">
          <OverviewCard label="Total Logs" :value="store.overview.totalLogs" />
          <OverviewCard label="Total Fingerprints" :value="store.overview.totalFingerprints" />
          <OverviewCard label="Known Patterns" :value="store.overview.knownPatterns" />
          <OverviewCard label="New Patterns" :value="store.overview.newPatterns" />
          <OverviewCard label="Anomalies Detected" :value="store.overview.anomaliesDetected" />
          <OverviewCard label="Exception Registered Count" :value="store.overview.exceptionRegisteredCount" />
        </div>
      </div>

      <div class="rounded-lg border border-slate-200 bg-white p-4 text-center shadow-sm">
        <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Risk Summary</h2>
        <p class="text-sm text-slate-500">Impact Score</p>
        <p class="text-5xl font-bold text-slate-900">{{ store.overview.riskScore }}</p>
        <p class="mt-1 text-lg font-semibold text-red-600">{{ store.overview.riskLevel }}</p>
        <p class="mt-4 text-sm text-slate-600">Detection Status: <span class="font-semibold">{{ store.overview.detectionStatus }}</span></p>
      </div>

      <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">Recommendation Summary</h2>
        <dl class="space-y-3 text-sm">
          <div><dt class="font-semibold text-slate-600">Cause</dt><dd>{{ store.recommendationSummary?.cause ?? '-' }}</dd></div>
          <div><dt class="font-semibold text-slate-600">Recommendation</dt><dd>{{ store.recommendationSummary?.recommendation ?? '-' }}</dd></div>
          <div><dt class="font-semibold text-slate-600">Confidence</dt><dd>{{ store.recommendationSummary?.confidence ?? '-' }}</dd></div>
        </dl>
      </div>
    </section>

    <LoadingSpinner v-if="store.loading" label="Running multi-agent analysis" />
    <ErrorState v-else-if="store.error" :message="store.error" />

    <template v-if="store.state">
      <div class="grid gap-6 xl:grid-cols-2">
        <PatternClusterTable :clusters="store.state.evidence.clusters" />
        <AnomalyTimelineChart :anomalies="store.state.evidence.anomalies" :logs="store.state.evidence.normalized_logs" />
      </div>
      <SourceCodePanel :stack-traces="store.state.evidence.stack_traces" />
      <RecommendationPanel
        :actions="store.state.final.recommended_actions ?? []"
        :verification="store.state.final.verification_steps ?? []"
        :generated-answer="store.state.final.generated_answer"
      />
      <AgentProgressTimeline :steps="store.agentTimeline" />
    </template>

    <EmptyState v-else-if="!store.loading" message="No analysis result yet. Trigger a run to populate the dashboard." />

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

    <div v-if="showServiceLayer" class="fixed inset-0 z-40 flex items-center justify-center bg-black/40" @click.self="showServiceLayer = false">
      <div class="w-full max-w-md rounded-lg bg-white p-4 shadow-xl">
        <div class="mb-3 flex items-center justify-between">
          <h3 class="text-base font-semibold text-slate-800">서비스 선택</h3>
          <button class="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100" @click="showServiceLayer = false">닫기</button>
        </div>
        <div v-if="store.loadingServices" class="py-8 text-center text-sm text-slate-500">서비스 목록 로딩중...</div>
        <div v-else-if="store.serviceOptions.length === 0" class="py-8 text-center text-sm text-slate-500">
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
import { onMounted, ref } from 'vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import OverviewCard from '@/components/dashboard/OverviewCard.vue'
import PatternClusterTable from '@/components/dashboard/PatternClusterTable.vue'
import AnomalyTimelineChart from '@/components/dashboard/AnomalyTimelineChart.vue'
import SourceCodePanel from '@/components/dashboard/SourceCodePanel.vue'
import RecommendationPanel from '@/components/dashboard/RecommendationPanel.vue'
import AgentProgressTimeline from '@/components/dashboard/AgentProgressTimeline.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useLogDetectStore } from '@/stores/logDetectStore'

const store = useLogDetectStore()
const serviceName = ref('')
const saveToChromaDb = ref(false)
const showServiceLayer = ref(false)

async function openServiceLayer() {
  await store.fetchServices()
  showServiceLayer.value = true
}

function handleSelectService(service: string) {
  serviceName.value = service
  showServiceLayer.value = false
}

function handleRunAnalysis() {
  const trimmed = serviceName.value.trim()
  if (!trimmed) return
  void store.runAnalysis(trimmed, saveToChromaDb.value)
}

onMounted(async () => {
  await store.fetchHealth()
  await store.fetchServices()
})
</script>
