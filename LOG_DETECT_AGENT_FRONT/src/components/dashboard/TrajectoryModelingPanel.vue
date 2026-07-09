<template>
  <section
    class="space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
  >
    <div class="flex items-center justify-between gap-3">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Trajectory Modeling Data
      </h2>
      <span class="text-xs text-slate-500">{{
        latestVector?.feature_schema_version ?? 'system-state-v1'
      }}</span>
    </div>

    <div class="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Merge Groups</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">
          {{ mergeGroups.length }}
        </p>
        <p class="mt-1 text-xs text-slate-500">
          {{ pendingMergeGroups }} pending approval
        </p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Time Windows</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">
          {{ eventWindows.length }}
        </p>
        <p class="mt-1 text-xs text-slate-500">
          {{ latestWindowLabel }}
        </p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">State Windows</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">
          {{ stateVectors.length }}
        </p>
        <p class="mt-1 text-xs text-slate-500">
          latest risk: {{ latestRiskLabel }}
        </p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Trajectories</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">
          {{ trajectories.length }}
        </p>
        <p class="mt-1 text-xs text-slate-500">{{ latestTrajectoryLabel }}</p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Clusters</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">
          {{ trajectoryClusters.length }}
        </p>
        <p class="mt-1 text-xs text-slate-500">
          {{ topCluster?.algorithm ?? '-' }}
        </p>
      </div>
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs uppercase text-slate-500">Nearest</p>
        <p class="mt-1 text-2xl font-semibold text-slate-900">
          {{ nearestSimilarity }}
        </p>
        <p class="mt-1 truncate text-xs text-slate-500">
          {{ nearestPattern?.cluster_id ?? '-' }}
        </p>
      </div>
    </div>

    <div
      v-if="latestVector"
      class="overflow-hidden rounded border border-slate-200"
    >
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
          <p class="mt-1 text-sm font-semibold text-slate-800">
            {{ latestTrajectory.label }}
          </p>
        </div>
        <span class="text-xs text-slate-500">
          {{ latestTrajectory.start_bucket }} ->
          {{ latestTrajectory.end_bucket }}
        </span>
      </div>

      <div class="mb-3 grid gap-2 md:grid-cols-5">
        <div
          v-for="item in latestTrajectorySummary"
          :key="item.label"
          class="rounded border border-slate-200 bg-slate-50 p-2"
        >
          <p class="text-xs text-slate-500">{{ item.label }}</p>
          <p class="mt-1 truncate text-sm font-semibold text-slate-800">
            {{ item.value }}
          </p>
          <p v-if="item.detail" class="mt-1 truncate text-xs text-slate-500">
            {{ item.detail }}
          </p>
        </div>
      </div>

      <div class="grid gap-2 md:grid-cols-3 xl:grid-cols-6">
        <div
          v-for="step in latestTrajectorySteps"
          :key="step.key"
          class="min-h-28 rounded border border-slate-200 bg-white p-2"
        >
          <div class="flex items-start justify-between gap-2">
            <div class="min-w-0">
              <p class="text-xs font-medium text-slate-500">
                {{ step.stepLabel }}
              </p>
              <p class="mt-1 truncate text-xs text-slate-500">
                {{ step.bucketLabel }}
              </p>
            </div>
            <span
              class="rounded px-2 py-0.5 text-xs font-semibold"
              :class="riskBadgeClass(step.risk)"
            >
              {{ step.risk }}
            </span>
          </div>
          <p class="mt-2 truncate text-sm font-semibold text-slate-800">
            {{ step.label }}
          </p>
          <div class="mt-2 grid grid-cols-2 gap-1 text-xs text-slate-600">
            <p>Events {{ step.events }}</p>
            <p>Anom {{ step.anomaly }}</p>
            <p>Error {{ step.errorRatio }}</p>
            <p>Warn {{ step.warnRatio }}</p>
          </div>
        </div>
      </div>
    </div>

    <div v-if="nearestPatterns.length" class="overflow-x-auto">
      <table class="min-w-full text-left text-sm">
        <thead
          class="border-b border-slate-200 text-xs uppercase text-slate-500"
        >
          <tr>
            <th class="py-2 pr-3">Similar Pattern</th>
            <th class="py-2 pr-3">Similarity</th>
            <th class="py-2 pr-3">Cluster</th>
            <th class="py-2 pr-3">Top FP</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="pattern in nearestPatterns.slice(0, 5)"
            :key="`${pattern.trajectory_id}-${pattern.cluster_id}`"
            class="border-b border-slate-100"
          >
            <td class="max-w-80 truncate py-2 pr-3 font-medium text-slate-800">
              {{ pattern.label }}
            </td>
            <td class="py-2 pr-3 text-slate-600">
              {{ percent(pattern.similarity) }}
            </td>
            <td class="max-w-56 truncate py-2 pr-3 text-slate-600">
              {{ pattern.cluster_id }}
            </td>
            <td class="max-w-56 truncate py-2 pr-3 text-slate-600">
              {{ topFingerprintLabel(pattern.top_fingerprints) }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="trajectoryClusters.length" class="overflow-x-auto">
      <table class="min-w-full text-left text-sm">
        <thead
          class="border-b border-slate-200 text-xs uppercase text-slate-500"
        >
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
            <td class="py-2 pr-3 font-medium text-slate-800">
              {{ cluster.cluster_id }}
            </td>
            <td class="max-w-80 truncate py-2 pr-3 text-slate-600">
              {{ cluster.label }}
            </td>
            <td class="py-2 pr-3 text-slate-600">{{ cluster.member_count }}</td>
            <td class="py-2 pr-3 text-slate-600">
              {{ cluster.max_risk_score }}
            </td>
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
        <thead
          class="border-b border-slate-200 text-xs uppercase text-slate-500"
        >
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
            <td class="py-2 pr-3 text-slate-600">
              {{ group.member_fingerprints.length }}
            </td>
            <td class="py-2 pr-3 text-slate-600">
              {{ group.total_occurrence_count }}
            </td>
            <td class="py-2 pr-3 text-slate-600">
              {{ percent(group.avg_similarity) }}
            </td>
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
const latestRiskLabel = computed(() => {
  const value = numberFeature(latestVector.value?.features, 'max_risk_score')
  return value === null ? '-' : String(Math.round(value))
})

const latestFeatureItems = computed(() => {
  const features = latestVector.value?.features ?? {}
  return [
    ['Events', features.total_events],
    ['Error Rate', ratioFeature(features.error_ratio)],
    ['Warn Rate', ratioFeature(features.warn_ratio)],
    ['Unique FP', features.unique_fingerprint_count],
    ['New FP Rate', ratioFeature(features.new_fingerprint_ratio)]
  ].map(([label, value]) => ({
    label: String(label),
    value:
      typeof value === 'number'
        ? Number(value).toFixed(value > 1 ? 0 : 3)
        : String(value ?? '-')
  }))
})

const stateVectorById = computed(() => {
  const pairs = stateVectors.value.map(
    (item) => [item.vector_id, item] as const
  )
  return new Map(pairs)
})

const latestTrajectorySteps = computed(() => {
  const item = latestTrajectory.value
  if (!item) return []
  return item.vector_ids.map((vectorId, index) => {
    const vector = stateVectorById.value.get(vectorId)
    const features = vector?.features ?? {}
    return {
      key: `${item.trajectory_id}-${index}`,
      stepLabel: `Step ${index + 1}`,
      bucketLabel: vector
        ? `${vector.bucket_size} ${vector.bucket_start}`
        : bucketFallback(item, index),
      label: vector?.label ?? labelForTrajectoryStep(item, index),
      events: formatInteger(numberFeature(features, 'total_events')),
      anomaly: formatInteger(numberFeature(features, 'anomaly_count')),
      risk: formatInteger(numberFeature(features, 'max_risk_score')),
      errorRatio: ratioFeature(features.error_ratio),
      warnRatio: ratioFeature(features.warn_ratio)
    }
  })
})

const latestTrajectorySummary = computed(() => {
  const item = latestTrajectory.value
  if (!item) return []
  const riskDelta = numberFeature(item.features, 'risk_delta')
  const startLabel = stringFeature(item.features, 'start_label') || '-'
  const endLabel = stringFeature(item.features, 'end_label') || '-'
  const nearest = nearestPattern.value
  return [
    {
      label: 'Flow',
      value: `${startLabel} -> ${endLabel}`,
      detail: `${item.window_length} ${item.bucket_size} windows`
    },
    {
      label: 'Risk Trend',
      value: riskTrendLabel(riskDelta),
      detail: riskDelta === null ? '-' : signedNumber(riskDelta)
    },
    {
      label: 'Max Risk',
      value: formatInteger(item.max_risk_score),
      detail: item.service_name || '-'
    },
    {
      label: 'Events',
      value: formatInteger(item.total_events),
      detail: `${formatInteger(item.anomaly_count)} anomalies`
    },
    {
      label: 'Nearest Pattern',
      value: nearest ? percent(nearest.similarity) : '-',
      detail: nearest?.label ?? topFingerprintLabel(item.top_fingerprints)
    }
  ]
})

function percent(value: number) {
  return `${Math.round((value || 0) * 100)}%`
}

function numberFeature(
  features: Record<string, number | string> | undefined,
  key: string
) {
  const value = features?.[key]
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function stringFeature(
  features: Record<string, number | string> | undefined,
  key: string
) {
  const value = features?.[key]
  if (typeof value === 'string') return value
  if (typeof value === 'number') return String(value)
  return ''
}

function ratioFeature(value: number | string | undefined) {
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return '-'
  return `${Math.round(numeric * 100)}%`
}

function formatInteger(value: number | null | undefined) {
  return value === null || value === undefined || !Number.isFinite(value)
    ? '-'
    : String(Math.round(value))
}

function signedNumber(value: number) {
  return value > 0 ? `+${Math.round(value)}` : String(Math.round(value))
}

function riskTrendLabel(value: number | null) {
  if (value === null) return '-'
  if (value >= 10) return 'Escalating'
  if (value <= -10) return 'Recovering'
  return 'Stable'
}

function bucketFallback(item: Trajectory, index: number) {
  if (index === 0) return item.start_bucket
  if (index === item.vector_ids.length - 1) return item.end_bucket
  return `${item.bucket_size} step`
}

function labelForTrajectoryStep(item: Trajectory, index: number) {
  if (index === 0)
    return stringFeature(item.features, 'start_label') || item.label
  if (index === item.vector_ids.length - 1)
    return stringFeature(item.features, 'end_label') || item.label
  return item.label
}

function riskBadgeClass(value: string) {
  const risk = Number(value)
  if (!Number.isFinite(risk)) return 'bg-slate-100 text-slate-600'
  if (risk >= 80) return 'bg-red-100 text-red-700'
  if (risk >= 50) return 'bg-amber-100 text-amber-700'
  return 'bg-emerald-100 text-emerald-700'
}

function topFingerprintLabel(
  items: Array<{ fingerprint: string; count: number }> = []
) {
  return (
    items
      .slice(0, 3)
      .map((item) => item.fingerprint)
      .join(' -> ') || '-'
  )
}

function similarityForCluster(clusterId: string) {
  const match = nearestPatterns.value.find(
    (item) => item.cluster_id === clusterId
  )
  return match ? percent(match.similarity) : '-'
}
</script>
