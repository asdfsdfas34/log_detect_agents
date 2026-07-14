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
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Trajectory Dashboard
            </p>
            <h2 class="mt-1 text-lg font-semibold text-slate-900">
              Time-window State Modeling
            </h2>
          </div>
          <div class="grid grid-cols-3 gap-3 text-sm">
            <OverviewCard label="Windows" :value="trajectoryEventWindows.length" />
            <OverviewCard label="Vectors" :value="trajectoryStateVectors.length" />
            <OverviewCard label="Clusters" :value="trajectoryClusters.length" />
          </div>
        </div>
      </div>

      <LoadingSpinner
        v-if="store.loading"
        label="Running trajectory modeling"
        :stage-log="store.currentExecutionLog"
      />
      <ErrorState v-else-if="store.error" :message="store.error" />

      <div v-if="store.state">
        <!-- Tabs: Trajectory Modeling (existing) vs RecFM Preview (new). -->
        <div
          role="tablist"
          aria-label="Trajectory dashboard views"
          class="flex gap-1 border-b border-slate-200"
          @keydown="onTabKeydown"
        >
          <button
            v-for="tab in tabs"
            :id="`tab-${tab.key}`"
            :key="tab.key"
            ref="tabButtons"
            role="tab"
            :aria-selected="store.activeTrajectoryTab === tab.key"
            :aria-controls="`tabpanel-${tab.key}`"
            :tabindex="store.activeTrajectoryTab === tab.key ? 0 : -1"
            class="-mb-px rounded-t border-b-2 px-4 py-2 text-sm font-medium focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            :class="
              store.activeTrajectoryTab === tab.key
                ? 'border-blue-600 text-blue-700'
                : 'border-transparent text-slate-500 hover:text-slate-700'
            "
            @click="store.activeTrajectoryTab = tab.key"
          >
            {{ tab.label }}
          </button>
        </div>

        <div
          v-show="store.activeTrajectoryTab === 'modeling'"
          id="tabpanel-modeling"
          role="tabpanel"
          aria-labelledby="tab-modeling"
          tabindex="0"
          class="pt-4"
        >
          <TrajectoryModelingPanel
            :merge-groups="trajectoryMergeGroups"
            :event-windows="trajectoryEventWindows"
            :state-vectors="trajectoryStateVectors"
            :trajectories="trajectories"
            :trajectory-clusters="trajectoryClusters"
            :nearest-patterns="nearestTrajectoryPatterns"
          />
        </div>

        <div
          v-show="store.activeTrajectoryTab === 'recfm'"
          id="tabpanel-recfm"
          role="tabpanel"
          aria-labelledby="tab-recfm"
          tabindex="0"
          class="pt-4"
        >
          <RecFMPreviewPanel
            :event-windows10min="eventWindows10min"
            :state-vectors10min="stateVectors10min"
            :trajectories10min="trajectories10min"
            :trajectory-clusters10min="trajectoryClusters10min"
            :available-buckets="availableBuckets"
            :window-length="recfmWindowLength"
          />
        </div>
      </div>

      <EmptyState
        v-if="!store.state && !store.loading"
        message="No trajectory modeling data yet. Trigger a run to populate this dashboard."
      />
    </section>

    <aside class="fixed left-4 top-28 z-20 hidden w-56 xl:block">
      <AgentProgressTimeline :steps="store.agentTimeline" compact />
    </aside>

    <aside class="fixed right-4 top-28 z-20 hidden w-80 2xl:block">
      <SkillActivityStreamPanel
        :items="store.skillActivityStream"
        :current="store.currentSkillActivity"
        :execution-status="store.executionStatus"
      />
    </aside>

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
import { computed, nextTick, onMounted, ref } from 'vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import OverviewCard from '@/components/dashboard/OverviewCard.vue'
import TrajectoryModelingPanel from '@/components/dashboard/TrajectoryModelingPanel.vue'
import RecFMPreviewPanel from '@/components/dashboard/RecFMPreviewPanel.vue'
import AgentProgressTimeline from '@/components/dashboard/AgentProgressTimeline.vue'
import SkillActivityStreamPanel from '@/components/dashboard/SkillActivityStreamPanel.vue'
import LoadingSpinner from '@/components/common/LoadingSpinner.vue'
import ErrorState from '@/components/common/ErrorState.vue'
import EmptyState from '@/components/common/EmptyState.vue'
import { useLogDetectStore } from '@/stores/logDetectStore'
import type {
  EventTimeWindow,
  FingerprintMergeGroup,
  NearestTrajectoryPattern,
  SystemStateVector,
  Trajectory,
  TrajectoryCluster
} from '@/types/agentTypes'

const store = useLogDetectStore()
const serviceName = ref('')
const analysisDate = ref(new Date().toISOString().slice(0, 10))
const showServiceLayer = ref(false)

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

const trajectories = computed(() => {
  const evidenceItems = store.state?.evidence.trajectories
  if (evidenceItems?.length) return evidenceItems
  return (evidenceBundle.value?.trajectories ?? []) as Trajectory[]
})

const trajectoryClusters = computed(() => {
  const evidenceItems = store.state?.evidence.trajectory_clusters
  if (evidenceItems?.length) return evidenceItems
  return (evidenceBundle.value?.trajectory_clusters ?? []) as TrajectoryCluster[]
})

const nearestTrajectoryPatterns = computed(() => {
  const evidenceItems = store.state?.evidence.nearest_trajectory_patterns
  if (evidenceItems?.length) return evidenceItems
  return (evidenceBundle.value?.nearest_trajectory_patterns ?? []) as NearestTrajectoryPattern[]
})

// --- RecFM Preview (10-minute bucket only) ---------------------------------
function evidence10min<T>(key: 'event_time_windows_10min' | 'system_state_vectors_10min' | 'trajectories_10min' | 'trajectory_clusters_10min'): T[] {
  const fromEvidence = store.state?.evidence[key]
  if (fromEvidence?.length) return fromEvidence as T[]
  return (evidenceBundle.value?.[key] ?? []) as T[]
}

const eventWindows10min = computed(() =>
  evidence10min<EventTimeWindow>('event_time_windows_10min')
)
const stateVectors10min = computed(() =>
  evidence10min<SystemStateVector>('system_state_vectors_10min')
)
const trajectories10min = computed(() => evidence10min<Trajectory>('trajectories_10min'))
const trajectoryClusters10min = computed(() =>
  evidence10min<TrajectoryCluster>('trajectory_clusters_10min')
)

const recfmWindowLength = computed(
  () => store.state?.evidence.recfm_trajectory_window_length ?? 6
)

// Buckets actually present in the analysis evidence (never fabricated).
const availableBuckets = computed(() => {
  const buckets = new Set<string>()
  for (const w of trajectoryEventWindows.value) if (w.bucket_size) buckets.add(w.bucket_size)
  for (const v of trajectoryStateVectors.value) if (v.bucket_size) buckets.add(v.bucket_size)
  if (eventWindows10min.value.length || stateVectors10min.value.length) buckets.add('10min')
  return Array.from(buckets).sort()
})

const tabs = [
  { key: 'modeling' as const, label: 'Trajectory Modeling' },
  { key: 'recfm' as const, label: 'RecFM Preview' }
]
const tabButtons = ref<HTMLButtonElement[]>([])

function onTabKeydown(event: KeyboardEvent) {
  const order = tabs.map((t) => t.key)
  const current = order.indexOf(store.activeTrajectoryTab)
  let next = current
  if (event.key === 'ArrowRight') next = (current + 1) % order.length
  else if (event.key === 'ArrowLeft') next = (current - 1 + order.length) % order.length
  else if (event.key === 'Home') next = 0
  else if (event.key === 'End') next = order.length - 1
  else return
  event.preventDefault()
  store.activeTrajectoryTab = order[next]
  void nextTick(() => tabButtons.value[next]?.focus())
}

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
  if (!trimmed || !analysisDate.value) return
  void store.runAnalysis(trimmed, analysisDate.value)
}

onMounted(async () => {
  await store.fetchHealth()
  await store.fetchServices()
})
</script>
