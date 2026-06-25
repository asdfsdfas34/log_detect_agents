<template>
  <section class="rounded-lg border bg-white p-4 shadow-sm">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-lg font-semibold">Pattern Clusters</h3>
        <p class="text-xs text-slate-500">
          Select a pattern action explicitly from the table.
        </p>
      </div>
      <div class="text-xs text-slate-500">
        {{ sortedClusters.length }} patterns
      </div>
    </div>

    <div class="overflow-x-auto">
      <table class="min-w-full table-fixed text-left text-sm">
        <thead class="text-xs uppercase text-slate-500">
          <tr>
            <th class="w-32 py-2">Cluster</th>
            <th class="py-2">Error Message</th>
            <th class="w-24 py-2">Level</th>
            <th class="w-36 py-2">Status</th>
            <th class="w-20 py-2 text-right">Count</th>
            <th class="w-28 py-2 text-right">Similarity</th>
            <th class="w-56 py-2 text-right">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in pagedClusters"
            :key="item.cluster"
            class="border-t"
          >
            <td
              class="py-2 font-mono text-xs"
              :class="isErrorLevel(item) ? 'font-semibold text-red-600' : ''"
            >
              {{ item.cluster }}
            </td>
            <td class="py-2 pr-4 text-slate-700">
              <button
                class="line-clamp-2 w-full text-left text-blue-700 hover:text-blue-900 hover:underline"
                type="button"
                @click="selectedCluster = item"
              >
                {{ item.message ?? 'No message captured for this pattern' }}
              </button>
            </td>
            <td class="py-2">
              <span
                class="rounded px-2 py-1 text-xs font-semibold"
                :class="levelClass(item.log_level)"
              >
                {{ item.log_level ?? '-' }}
              </span>
            </td>
            <td class="py-2">
              <span
                class="rounded px-2 py-1 text-xs font-semibold"
                :class="statusClass(item.pattern_status)"
              >
                {{ statusLabel(item.pattern_status) }}
              </span>
            </td>
            <td class="py-2 text-right tabular-nums">{{ item.count }}</td>
            <td class="py-2 text-right">
              <div class="font-semibold text-slate-700">
                {{ similarity(item) }}%
              </div>
              <div
                v-if="item.similar_clusters?.length"
                class="text-xs text-slate-400"
              >
                {{ item.similar_clusters.length }} matches
              </div>
            </td>
            <td class="py-2 text-right">
              <div class="flex justify-end gap-2">
                <button
                  class="rounded border border-emerald-200 px-2 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-50"
                  type="button"
                  @click="emit('save-known-pattern', item)"
                >
                  Known Pattern
                </button>
                <button
                  class="rounded border border-blue-200 px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50"
                  type="button"
                  @click="emit('request-recommendation', item)"
                >
                  Recommendation
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="pagedClusters.length === 0">
            <td class="border-t py-8 text-center text-sm text-slate-500" colspan="7">
              No pattern clusters found.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div
      v-if="pageCount > 1"
      class="mt-3 flex flex-wrap items-center justify-between gap-3 border-t pt-3 text-sm"
    >
      <p class="text-xs text-slate-500">
        Page {{ currentPage }} of {{ pageCount }}
      </p>
      <div class="flex items-center gap-2">
        <button
          class="rounded border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          :disabled="currentPage === 1"
          @click="currentPage -= 1"
        >
          Previous
        </button>
        <button
          v-for="page in visiblePages"
          :key="page"
          class="h-8 w-8 rounded border text-xs font-semibold"
          type="button"
          :class="
            page === currentPage
              ? 'border-blue-600 bg-blue-600 text-white'
              : 'border-slate-300 text-slate-700 hover:bg-slate-50'
          "
          @click="currentPage = page"
        >
          {{ page }}
        </button>
        <button
          class="rounded border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          :disabled="currentPage === pageCount"
          @click="currentPage += 1"
        >
          Next
        </button>
      </div>
    </div>

    <div
      v-if="selectedCluster"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="selectedCluster = null"
    >
      <div class="max-h-[85vh] w-full max-w-4xl overflow-hidden rounded-lg bg-white shadow-xl">
        <div class="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h4 class="text-base font-semibold text-slate-900">
              {{ selectedCluster.cluster }}
            </h4>
            <p class="text-xs text-slate-500">Pattern details</p>
          </div>
          <button
            class="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
            type="button"
            @click="selectedCluster = null"
          >
            Close
          </button>
        </div>

        <div class="max-h-[calc(85vh-64px)] space-y-4 overflow-y-auto p-4">
          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Error Message
            </h5>
            <pre class="whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800">{{ selectedCluster.message || '-' }}</pre>
          </section>

          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Stack Trace
            </h5>
            <pre class="whitespace-pre-wrap rounded border border-slate-200 bg-slate-950 p-3 text-xs text-slate-100">{{ selectedCluster.stacktrace || '-' }}</pre>
          </section>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type { Cluster } from '@/types/agentTypes'

const PAGE_SIZE = 10

const props = defineProps<{ clusters: Cluster[] }>()
const emit = defineEmits<{
  'save-known-pattern': [cluster: Cluster]
  'request-recommendation': [cluster: Cluster]
}>()

const currentPage = ref(1)
const selectedCluster = ref<Cluster | null>(null)

const sortedClusters = computed(() =>
  [...props.clusters].sort((a, b) => b.count - a.count)
)

const pageCount = computed(() =>
  Math.max(1, Math.ceil(sortedClusters.value.length / PAGE_SIZE))
)

const pagedClusters = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return sortedClusters.value.slice(start, start + PAGE_SIZE)
})

const visiblePages = computed(() => {
  const pages: number[] = []
  const start = Math.max(1, currentPage.value - 2)
  const end = Math.min(pageCount.value, start + 4)
  for (let page = start; page <= end; page += 1) pages.push(page)
  return pages
})

watch(
  () => props.clusters,
  () => {
    currentPage.value = 1
  }
)

watch(pageCount, (count) => {
  if (currentPage.value > count) currentPage.value = count
})

function similarity(item: Cluster): number {
  return item.semantic_similarity ?? 0
}

function isErrorLevel(item: Cluster): boolean {
  return item.log_level === 'ERROR'
}

function levelClass(level?: string): string {
  if (level === 'ERROR') return 'bg-red-100 text-red-700'
  if (level === 'WARN') return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-600'
}

function statusLabel(status?: string): string {
  if (status === 'known_exact') return 'Known Exact'
  if (status === 'known_similar') return 'Known Similar'
  if (status === 'observed_existing') return 'Observed'
  if (status === 'new_pattern') return 'New'
  return '-'
}

function statusClass(status?: string): string {
  if (status === 'known_exact') return 'bg-emerald-100 text-emerald-700'
  if (status === 'known_similar') return 'bg-cyan-100 text-cyan-700'
  if (status === 'observed_existing') return 'bg-slate-100 text-slate-700'
  if (status === 'new_pattern') return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-500'
}
</script>
