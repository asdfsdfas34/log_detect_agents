<template>
  <section class="space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between gap-3">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Trajectory Modeling Data
      </h2>
      <span class="text-xs text-slate-500">{{ latestVector?.feature_schema_version ?? 'system-state-v1' }}</span>
    </div>

    <div class="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Merge Groups</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">{{ mergeGroups.length }}</p>
        <p class="mt-1 text-xs text-slate-500">
          {{ pendingMergeGroups }} pending approval
        </p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Time Windows</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">{{ eventWindows.length }}</p>
        <p class="mt-1 text-xs text-slate-500">
          {{ latestWindowLabel }}
        </p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">State Vectors</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">{{ stateVectors.length }}</p>
        <p class="mt-1 text-xs text-slate-500">
          latest label: {{ latestVector?.label ?? '-' }}
        </p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Trajectories</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">{{ trajectories.length }}</p>
        <p class="mt-1 text-xs text-slate-500">{{ latestTrajectoryLabel }}</p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Clusters</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">{{ trajectoryClusters.length }}</p>
        <p class="mt-1 text-xs text-slate-500">{{ topCluster?.algorithm ?? '-' }}</p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Nearest</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">{{ nearestSimilarity }}</p>
        <p class="mt-1 truncate text-xs text-slate-500">{{ nearestPattern?.cluster_id ?? '-' }}</p>
      </div>
    </div>

    <div v-if="latestVector" class="overflow-hidden rounded border border-slate-200">
      <div class="grid grid-cols-2 gap-px bg-slate-200 text-sm md:grid-cols-5">
        <div
          v-for="item in latestFeatureItems"
          :key="item.label"
          class="bg-white p-3"
        >
          <p class="text-xs text-slate-500">{{ item.label }}</p>
          <p class="mt-1 font-semibold text-slate-800">{{ item.value }}</p>
        </div>
      </div>
    </div>

    <div v-if="latestTrajectory" class="rounded border border-slate-200 p-3">
      <div class="mb-3 flex items-center justify-between gap-3">
        <div>
          <p class="text-xs uppercase text-slate-500">Latest Trajectory</p>
          <p class="mt-1 text-sm font-semibold text-slate-800">{{ latestTrajectory.label }}</p>
        </div>
        <span class="text-xs text-slate-500">
          {{ latestTrajectory.start_bucket }} -> {{ latestTrajectory.end_bucket }}
        </span>
      </div>
      <div class="grid gap-2 md:grid-cols-6">
        <div
          v-for="(vectorId, index) in latestTrajectory.vector_ids"
          :key="`${latestTrajectory.trajectory_id}-${vectorId}`"
          class="min-h-14 rounded border border-slate-200 bg-slate-50 p-2"
        >
          <p class="text-xs text-slate-500">t-{{ latestTrajectory.vector_ids.length - index - 1 }}</p>
          <p class="mt-1 truncate text-xs font-medium text-slate-700">{{ vectorId }}</p>
        </div>
      </div>
    </div>

    <div v-if="trajectoryClusters.length" class="overflow-x-auto">
      <table class="min-w-full text-left text-sm">
        <thead class="border-b border-slate-200 text-xs uppercase text-slate-500">
          <tr>
            <th class="py-2 pr-3">Cluster</th>
            <th class="py-2 pr-3">Label</th>
            <th class="py-2 pr-3">Members</th>
            <th class="py-2 pr-3">Risk</th>
            <th class="py-2 pr-3">Top FP</th>
            <th class="py-2 pr-3">Similarity</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="cluster in trajectoryClusters.slice(0, 5)"
            :key="cluster.cluster_id"
            class="border-b border-slate-100"
          >
            <td class="py-2 pr-3 font-medium text-slate-800">{{ cluster.cluster_id }}</td>
            <td class="max-w-80 truncate py-2 pr-3 text-slate-600">{{ cluster.label }}</td>
            <td class="py-2 pr-3 text-slate-600">{{ cluster.member_count }}</td>
            <td class="py-2 pr-3 text-slate-600">{{ cluster.max_risk_score }}</td>
            <td class="max-w-56 truncate py-2 pr-3 text-slate-600">
              {{ topFingerprintLabel(cluster.top_fingerprints) }}
            </td>
            <td class="py-2 pr-3 text-slate-600">
              {{ similarityForCluster(cluster.cluster_id) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="mergeGroups.length" class="overflow-x-auto">
      <table class="min-w-full text-left text-sm">
        <thead class="border-b border-slate-200 text-xs uppercase text-slate-500">
          <tr>
            <th class="py-2 pr-3">Canonical FP</th>
            <th class="py-2 pr-3">Members</th>
            <th class="py-2 pr-3">Count</th>
            <th class="py-2 pr-3">Confidence</th>
            <th class="py-2 pr-3">Status</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="group in mergeGroups.slice(0, 5)"
            :key="group.group_id"
            class="border-b border-slate-100"
          >
            <td class="max-w-56 truncate py-2 pr-3 font-medium text-slate-800">
              {{ group.canonical_fingerprint }}
            </td>
            <td class="py-2 pr-3 text-slate-600">{{ group.member_fingerprints.length }}</td>
            <td class="py-2 pr-3 text-slate-600">{{ group.total_occurrence_count }}</td>
            <td class="py-2 pr-3 text-slate-600">{{ percent(group.avg_similarity) }}</td>
            <td class="py-2 pr-3 text-slate-600">{{ group.status }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type {
  EventTimeWindow,
  FingerprintMergeGroup,
  NearestTrajectoryPattern,
  SystemStateVector,
  Trajectory,
  TrajectoryCluster
} from '@/types/agentTypes'

const props = defineProps<{
  mergeGroups?: FingerprintMergeGroup[]
  eventWindows?: EventTimeWindow[]
  stateVectors?: SystemStateVector[]
  trajectories?: Trajectory[]
  trajectoryClusters?: TrajectoryCluster[]
  nearestPatterns?: NearestTrajectoryPattern[]
}>()

const mergeGroups = computed(() => props.mergeGroups ?? [])
const eventWindows = computed(() => props.eventWindows ?? [])
const stateVectors = computed(() => props.stateVectors ?? [])
const trajectories = computed(() => props.trajectories ?? [])
const trajectoryClusters = computed(() => props.trajectoryClusters ?? [])
const nearestPatterns = computed(() => props.nearestPatterns ?? [])

const pendingMergeGroups = computed(
  () => mergeGroups.value.filter((group) => group.status === 'pending').length
)

const latestVector = computed(() => stateVectors.value[0])
const latestWindow = computed(() => eventWindows.value[0])
const latestTrajectory = computed(() => trajectories.value[0])
const topCluster = computed(() => trajectoryClusters.value[0])
const nearestPattern = computed(() => nearestPatterns.value[0])
const latestWindowLabel = computed(() => {
  const item = latestWindow.value
  if (!item) return '-'
  return `${item.bucket_size} ${item.bucket_start}`
})
const latestTrajectoryLabel = computed(() => {
  const item = latestTrajectory.value
  if (!item) return '-'
  return `${item.window_length} ${item.bucket_size} windows`
})
const nearestSimilarity = computed(() => {
  const item = nearestPattern.value
  if (!item) return '-'
  return percent(item.similarity)
})

const latestFeatureItems = computed(() => {
  const features = latestVector.value?.features ?? {}
  return [
    ['events', features.total_events],
    ['error ratio', features.error_ratio],
    ['warn ratio', features.warn_ratio],
    ['unique fp', features.unique_fingerprint_count],
    ['risk', features.max_risk_score]
  ].map(([label, value]) => ({
    label: String(label),
    value: typeof value === 'number' ? Number(value).toFixed(value > 1 ? 0 : 3) : '-'
  }))
})

function percent(value: number) {
  return `${Math.round((value || 0) * 100)}%`
}

function topFingerprintLabel(items: Array<{ fingerprint: string; count: number }> = []) {
  return items
    .slice(0, 3)
    .map((item) => item.fingerprint)
    .join(' -> ') || '-'
}

function similarityForCluster(clusterId: string) {
  const match = nearestPatterns.value.find((item) => item.cluster_id === clusterId)
  return match ? percent(match.similarity) : '-'
}
</script>
