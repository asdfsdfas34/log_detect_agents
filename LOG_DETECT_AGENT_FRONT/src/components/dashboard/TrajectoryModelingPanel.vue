<template>
  <section class="space-y-4 rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="flex items-center justify-between gap-3">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
        Trajectory Modeling Data
      </h2>
      <span class="text-xs text-slate-500">{{ latestVector?.feature_schema_version ?? 'system-state-v1' }}</span>
    </div>

    <div class="grid gap-3 md:grid-cols-3">
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
  SystemStateVector
} from '@/types/agentTypes'

const props = defineProps<{
  mergeGroups?: FingerprintMergeGroup[]
  eventWindows?: EventTimeWindow[]
  stateVectors?: SystemStateVector[]
}>()

const mergeGroups = computed(() => props.mergeGroups ?? [])
const eventWindows = computed(() => props.eventWindows ?? [])
const stateVectors = computed(() => props.stateVectors ?? [])

const pendingMergeGroups = computed(
  () => mergeGroups.value.filter((group) => group.status === 'pending').length
)

const latestVector = computed(() => stateVectors.value[0])
const latestWindow = computed(() => eventWindows.value[0])
const latestWindowLabel = computed(() => {
  const item = latestWindow.value
  if (!item) return '-'
  return `${item.bucket_size} ${item.bucket_start}`
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
</script>
