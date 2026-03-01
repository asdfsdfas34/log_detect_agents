<template>
  <AppLayout>
    <template #header-right>
      <div class="flex items-center gap-3">
        <input
          v-model="serviceName"
          type="text"
          placeholder="서비스 이름 입력 (예: auth-api)"
          class="w-56 rounded border border-slate-300 px-3 py-2 text-sm"
        />
        <div class="text-right text-xs text-slate-600">
          <p>Status: <span class="font-semibold">{{ store.executionStatus }}</span></p>
          <p>Stage: <span class="font-semibold">{{ store.currentStage }}</span></p>
          <p>Last run: {{ store.lastExecutionAt ?? '-' }}</p>
        </div>
        <button
          class="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          :disabled="store.loading || !serviceName.trim()"
          @click="handleRunAnalysis"
        >
          Re-run analysis
        </button>
      </div>
    </template>

    <section class="grid gap-4 md:grid-cols-3 xl:grid-cols-6">
      <OverviewCard label="Total logs" :value="store.overview.totalLogs" />
      <OverviewCard label="Anomalies" :value="store.overview.totalAnomalies" />
      <OverviewCard label="Unique patterns" :value="store.overview.uniquePatterns" />
      <OverviewCard label="Impact score" :value="store.overview.impactScore" />
      <OverviewCard label="Risk" :value="store.riskClassification" />
      <OverviewCard label="System health" :value="store.healthStatus" :subtitle="store.healthModel" />
    </section>

    <LoadingSpinner v-if="store.loading" label="Running multi-agent analysis" />
    <ErrorState v-else-if="store.error" :message="store.error" />

    <template v-if="store.state">
      <ImpactGauge :score="store.overview.impactScore" :metrics="store.state.metrics" />
      <div class="grid gap-6 xl:grid-cols-2">
        <PatternClusterTable :clusters="store.state.evidence.clusters" />
        <AnomalyTimelineChart :anomalies="store.state.evidence.anomalies" :logs="store.state.evidence.normalized_logs" />
      </div>
      <SourceCodePanel :stack-traces="store.state.evidence.stack_traces" />
      <RecommendationPanel
        :actions="store.state.final.recommended_actions ?? []"
        :verification="store.state.final.verification_steps ?? []"
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
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import OverviewCard from '@/components/dashboard/OverviewCard.vue'
import ImpactGauge from '@/components/dashboard/ImpactGauge.vue'
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
const serviceName = ref('billing-api')

function handleRunAnalysis() {
  const trimmed = serviceName.value.trim()
  if (!trimmed) return
  void store.runAnalysis(trimmed)
}

onMounted(async () => {
  await store.fetchHealth()
})
</script>
