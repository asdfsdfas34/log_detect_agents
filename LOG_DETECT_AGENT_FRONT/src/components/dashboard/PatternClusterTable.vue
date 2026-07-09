<template>
  <section class="rounded-lg border bg-white p-4 shadow-sm">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-lg font-semibold">Pattern Clusters</h3>
        <p class="text-xs text-slate-500">
          Select a pattern action explicitly from the table.
        </p>
      </div>
      <div class="text-right text-xs text-slate-500">
        {{ formatCount(activeClusters.length) }} patterns /
        {{ formatCount(activeLogCount) }} logs
      </div>
    </div>
    <div
      class="mb-3 flex flex-wrap items-center justify-between gap-3 rounded border border-slate-200 bg-slate-50 px-3 py-2"
    >
      <p class="text-xs text-slate-600">
        {{ selectedFingerprints.length }} fingerprints selected
      </p>
      <div class="flex gap-2">
        <button
          class="rounded border border-slate-300 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-white disabled:cursor-not-allowed disabled:opacity-50"
          type="button"
          :disabled="selectedFingerprints.length === 0"
          @click="selectedFingerprints = []"
        >
          Clear
        </button>
        <button
          class="rounded bg-emerald-600 px-3 py-1 text-xs font-semibold text-white hover:bg-emerald-700 disabled:cursor-not-allowed disabled:bg-slate-300"
          type="button"
          :disabled="selectedFingerprints.length < 2"
          @click="requestManualMergeKnown"
        >
          Merge + Known
        </button>
      </div>
    </div>

    <div
      v-if="patternClusters.length"
      class="mb-4 rounded border border-blue-100 bg-blue-50/60 p-3"
    >
      <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h4 class="text-sm font-semibold text-blue-900">
          Canonical Pattern Clusters
        </h4>
        <span class="text-xs font-semibold text-blue-700">
          {{ formatCount(patternClusters.length) }} clusters
        </span>
      </div>
      <div class="grid gap-2 md:grid-cols-2">
        <article
          v-for="cluster in visiblePatternClusters"
          :key="cluster.cluster_id"
          class="rounded border border-blue-100 bg-white p-3"
        >
          <div class="mb-2 flex flex-wrap items-start justify-between gap-2">
            <div>
              <p class="font-mono text-xs font-semibold text-slate-700">
                {{ cluster.cluster_id }}
              </p>
              <p class="mt-1 line-clamp-2 text-xs text-slate-600">
                {{ cluster.representative_template || cluster.representative_message }}
              </p>
            </div>
            <span
              class="rounded bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700"
            >
              {{ cluster.member_count }} members
            </span>
          </div>
          <dl class="grid grid-cols-2 gap-2 text-xs text-slate-600">
            <div>
              <dt class="font-semibold text-slate-500">Canonical</dt>
              <dd class="break-all font-mono">{{ cluster.canonical_fingerprint }}</dd>
            </div>
            <div>
              <dt class="font-semibold text-slate-500">Algorithm</dt>
              <dd>{{ cluster.algorithm }}</dd>
            </div>
            <div>
              <dt class="font-semibold text-slate-500">Pattern Avg</dt>
              <dd>{{ percent(cluster.avg_pattern_similarity) }}%</dd>
            </div>
            <div>
              <dt class="font-semibold text-slate-500">Semantic Max</dt>
              <dd>{{ percent(cluster.max_semantic_similarity) }}%</dd>
            </div>
            <div>
              <dt class="font-semibold text-slate-500">Links</dt>
              <dd>{{ cluster.links.length }}</dd>
            </div>
            <div>
              <dt class="font-semibold text-slate-500">Logs</dt>
              <dd>{{ cluster.total_occurrence_count }}</dd>
            </div>
          </dl>
        </article>
      </div>
    </div>

    <div class="mb-4 flex flex-wrap gap-2 border-b border-slate-200">
      <button
        v-for="tab in tabs"
        :key="tab.key"
        class="-mb-px border-b-2 px-3 py-2 text-sm font-semibold"
        type="button"
        :class="
          activeTab === tab.key
            ? 'border-blue-600 text-blue-700'
            : 'border-transparent text-slate-500 hover:text-slate-800'
        "
        @click="activeTab = tab.key"
      >
        {{ tab.label }}
        <span
          class="ml-1 rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600"
        >
          {{ tab.count }}
        </span>
      </button>
    </div>

    <div
      v-if="activeTab === 'anomaly'"
      class="mb-4 flex flex-wrap gap-2 rounded border border-slate-200 bg-slate-50 p-2"
    >
      <button
        v-for="tab in anomalyTabs"
        :key="tab.key"
        class="rounded px-3 py-1.5 text-xs font-semibold"
        type="button"
        :class="
          activeAnomalyTab === tab.key
            ? 'bg-red-600 text-white'
            : 'bg-white text-slate-600 hover:text-slate-900'
        "
        @click="activeAnomalyTab = tab.key"
      >
        {{ tab.label }}
        <span
          class="ml-1 rounded px-1.5 py-0.5 text-[11px]"
          :class="
            activeAnomalyTab === tab.key
              ? 'bg-white/20 text-white'
              : 'bg-slate-100 text-slate-500'
          "
        >
          {{ tab.count }}
        </span>
      </button>
    </div>

    <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div class="relative w-full sm:max-w-md">
        <input
          v-model="searchQuery"
          type="search"
          class="w-full rounded border border-slate-300 bg-white px-3 py-2 pr-9 text-sm text-slate-700 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-100"
          placeholder="Search cluster, message, level, status"
          aria-label="Search pattern clusters"
        />
        <button
          v-if="searchQuery"
          class="absolute right-2 top-1/2 h-6 w-6 -translate-y-1/2 rounded text-sm font-semibold text-slate-400 hover:bg-slate-100 hover:text-slate-700"
          type="button"
          aria-label="Clear pattern cluster search"
          @click="searchQuery = ''"
        >
          x
        </button>
      </div>
      <p v-if="searchQuery" class="text-xs text-slate-500">
        {{ formatCount(activeClusters.length) }} of
        {{ formatCount(tabClusters.length) }} patterns
      </p>
    </div>

    <div class="overflow-x-auto">
      <table class="min-w-full table-fixed text-left text-sm">
        <thead class="text-xs uppercase text-slate-500">
          <tr>
            <th class="w-10 py-2">
              <input
                type="checkbox"
                :checked="pageSelectionState === 'all'"
                :indeterminate="pageSelectionState === 'partial'"
                aria-label="Select visible fingerprints"
                @change="togglePageSelection"
              />
            </th>
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
            <td class="py-2">
              <input
                type="checkbox"
                :checked="selectedFingerprints.includes(item.cluster)"
                :aria-label="`Select ${item.cluster}`"
                @change="toggleFingerprint(item.cluster)"
              />
            </td>
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
              <div
                v-if="activeTab === 'anomaly'"
                class="mt-1 rounded border border-red-100 bg-red-50 px-2 py-1 text-xs text-red-700"
              >
                <span class="font-semibold">{{ anomalyTypeLabel(item) }}</span>
                <span v-if="anomalyReason(item)"> · {{ anomalyReason(item) }}</span>
              </div>
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
              <button
                v-if="item.pattern_status === 'known_similar'"
                class="rounded px-2 py-1 text-xs font-semibold hover:ring-2 hover:ring-cyan-200"
                :class="statusClass(item.pattern_status)"
                type="button"
                @click="openSimilarCluster(item)"
              >
                {{ statusLabel(item.pattern_status) }}
              </button>
              <span
                v-else
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
              <button
                class="text-xs font-semibold text-cyan-700 hover:text-cyan-900 hover:underline"
                type="button"
                :disabled="!props.serviceName || similarLoadingKey === item.cluster"
                @click="openSimilarCluster(item)"
              >
                <span v-if="similarLoadingKey === item.cluster">Loading...</span>
                <span v-else-if="item.similar_clusters?.length">
                  {{ item.similar_clusters.length }} matches
                </span>
                <span v-else>Load matches</span>
              </button>
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
                  :disabled="props.recommendationBusyFingerprint === item.cluster"
                  :class="
                    props.recommendationBusyFingerprint === item.cluster
                      ? 'cursor-not-allowed opacity-60'
                      : ''
                  "
                  @click="emit('request-recommendation', item)"
                >
                  {{
                    props.recommendationBusyFingerprint === item.cluster
                      ? 'Generating...'
                      : 'Recommendation'
                  }}
                </button>
                <button
                  class="rounded border border-violet-200 px-2 py-1 text-xs font-semibold text-violet-700 hover:bg-violet-50"
                  type="button"
                  @click="emit('suggest-pattern-rule', item)"
                >
                  Pattern Rule
                </button>
              </div>
            </td>
          </tr>
          <tr v-if="pagedClusters.length === 0">
            <td
              class="border-t py-8 text-center text-sm text-slate-500"
              colspan="8"
            >
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
      <div
        class="max-h-[85vh] w-full max-w-4xl overflow-hidden rounded-lg bg-white shadow-xl"
      >
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
          <section v-if="selectedCluster.anomaly_detected">
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Detection Reason
            </h5>
            <div class="rounded border border-red-100 bg-red-50 p-3 text-sm text-red-800">
              <div class="font-semibold">{{ anomalyTypeLabel(selectedCluster) }}</div>
              <div class="mt-1">{{ anomalyReason(selectedCluster) || '-' }}</div>
            </div>
          </section>

          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Error Message
            </h5>
            <pre
              class="whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800"
              >{{ selectedCluster.message || '-' }}</pre
            >
          </section>

          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Stack Trace
            </h5>
            <pre
              class="whitespace-pre-wrap rounded border border-slate-200 bg-slate-950 p-3 text-xs text-slate-100"
              >{{ selectedCluster.stacktrace || '-' }}</pre
            >
          </section>
        </div>
      </div>
    </div>

    <div
      v-if="selectedSimilarCluster"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="selectedSimilarCluster = null"
    >
      <div
        class="max-h-[85vh] w-full max-w-5xl overflow-hidden rounded-lg bg-white shadow-xl"
      >
        <div class="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h4 class="text-base font-semibold text-slate-900">
              {{ selectedSimilarCluster.cluster }}
            </h4>
            <p class="text-xs text-slate-500">Similar pattern matches</p>
          </div>
          <button
            class="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
            type="button"
            @click="selectedSimilarCluster = null"
          >
            Close
          </button>
        </div>

        <div class="max-h-[calc(85vh-64px)] space-y-4 overflow-y-auto p-4">
          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Current Pattern
            </h5>
            <pre
              class="max-h-36 overflow-y-auto whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800"
              >{{ selectedSimilarCluster.message || '-' }}</pre
            >
          </section>

          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Matched Patterns
            </h5>
            <p
              v-if="similarLoadingKey === selectedSimilarCluster.cluster"
              class="rounded border border-slate-200 p-4 text-sm text-slate-500"
            >
              Loading similar pattern details...
            </p>
            <p
              v-else-if="similarError"
              class="rounded border border-red-100 bg-red-50 p-4 text-sm text-red-700"
            >
              {{ similarError }}
            </p>
            <div
              v-else-if="selectedSimilarCluster.similar_clusters?.length"
              class="space-y-3"
            >
              <article
                v-for="(match, index) in selectedSimilarCluster.similar_clusters"
                :key="similarMatchKey(match, index)"
                class="rounded border border-slate-200 p-3"
              >
                <div class="mb-2 flex flex-wrap items-center justify-between gap-2">
                  <div class="font-mono text-xs font-semibold text-slate-700">
                    {{ similarMatchId(match) }}
                  </div>
                  <div class="flex items-center gap-2">
                    <span
                      class="rounded bg-cyan-100 px-2 py-1 text-xs font-semibold text-cyan-700"
                    >
                      {{ similarMatchPercent(match) }}%
                    </span>
                    <button
                      class="rounded border border-emerald-200 px-2 py-1 text-xs font-semibold text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
                      type="button"
                      :disabled="!canMergeSimilarMatch(match)"
                      @click="requestMergeKnownForSimilarMatch(match)"
                    >
                      Merge + Known
                    </button>
                  </div>
                </div>
                <dl class="grid gap-2 text-xs text-slate-600 md:grid-cols-3">
                  <div>
                    <dt class="font-semibold text-slate-500">Fingerprint</dt>
                    <dd class="break-all">{{ similarMatchFingerprint(match) }}</dd>
                  </div>
                  <div>
                    <dt class="font-semibold text-slate-500">Service</dt>
                    <dd>{{ similarMatchMetadata(match, 'service_name') }}</dd>
                  </div>
                  <div>
                    <dt class="font-semibold text-slate-500">Level</dt>
                    <dd>{{ similarMatchMetadata(match, 'log_level') }}</dd>
                  </div>
                </dl>
                <pre
                  class="mt-3 max-h-44 overflow-y-auto whitespace-pre-wrap rounded bg-slate-50 p-3 text-xs text-slate-700"
                  >{{ similarMatchDocument(match) }}</pre
                >
              </article>
            </div>
            <p v-else class="rounded border border-slate-200 p-4 text-sm text-slate-500">
              No similar pattern details available.
            </p>
          </section>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { agentApi } from '@/api/agentApi'
import type { Cluster, PatternCluster } from '@/types/agentTypes'

const PAGE_SIZE = 10
type PatternTab = 'similar' | 'new' | 'known' | 'observed' | 'anomaly'
type AnomalyTab = 'all' | 'decrease' | 'increase' | 'absence' | 'recurrence'

const props = defineProps<{
  clusters: Cluster[]
  patternClusters?: PatternCluster[]
  serviceName: string
  recommendationBusyFingerprint?: string | null
}>()
const emit = defineEmits<{
  'save-known-pattern': [cluster: Cluster]
  'request-recommendation': [cluster: Cluster]
  'suggest-pattern-rule': [cluster: Cluster]
  'manual-merge-known': [fingerprints: string[]]
}>()

const currentPage = ref(1)
const selectedCluster = ref<Cluster | null>(null)
const selectedSimilarCluster = ref<Cluster | null>(null)
const similarLoadingKey = ref<string | null>(null)
const similarError = ref('')
const activeTab = ref<PatternTab>('similar')
const activeAnomalyTab = ref<AnomalyTab>('all')
const selectedFingerprints = ref<string[]>([])
const searchQuery = ref('')

const sortedClusters = computed(() =>
  [...props.clusters].sort((a, b) => b.count - a.count)
)

const patternClusters = computed(() => props.patternClusters ?? [])

const visiblePatternClusters = computed(() => patternClusters.value.slice(0, 4))

const knownClusters = computed(() =>
  sortedClusters.value.filter((cluster) => cluster.pattern_status === 'known_exact')
)

const similarClusters = computed(() =>
  sortedClusters.value.filter(
    (cluster) => cluster.pattern_status === 'known_similar'
  )
)

const newClusters = computed(() =>
  sortedClusters.value.filter(
    (cluster) => cluster.pattern_status === 'new_pattern'
  )
)

const observedClusters = computed(() =>
  sortedClusters.value.filter(
    (cluster) => cluster.pattern_status === 'observed_existing'
  )
)

const anomalyClusters = computed(() =>
  sortedClusters.value.filter(
    (cluster) =>
      cluster.anomaly_detected && cluster.pattern_status !== 'new_pattern'
  )
)

const filteredAnomalyClusters = computed(() => {
  if (activeAnomalyTab.value === 'all') return anomalyClusters.value
  return anomalyClusters.value.filter(
    (cluster) => anomalyTabFor(cluster) === activeAnomalyTab.value
  )
})

const anomalyTabs = computed(() => [
  {
    key: 'all' as const,
    label: 'ALL',
    count: anomalyClusters.value.length
  },
  {
    key: 'decrease' as const,
    label: 'Pattern Decrease',
    count: anomalyCountByTab('decrease')
  },
  {
    key: 'increase' as const,
    label: 'Pattern Increase',
    count: anomalyCountByTab('increase')
  },
  {
    key: 'absence' as const,
    label: 'Pattern Absence',
    count: anomalyCountByTab('absence')
  },
  {
    key: 'recurrence' as const,
    label: 'Pattern Reccur',
    count: anomalyCountByTab('recurrence')
  }
])

const tabs = computed(() => [
  {
    key: 'similar' as const,
    label: 'Similar Pattern',
    count: similarClusters.value.length
  },
  {
    key: 'known' as const,
    label: 'Known Pattern',
    count: knownClusters.value.length
  },
  {
    key: 'new' as const,
    label: 'New Pattern',
    count: newClusters.value.length
  },
  {
    key: 'observed' as const,
    label: 'Observed Existing',
    count: observedClusters.value.length
  },
  {
    key: 'anomaly' as const,
    label: 'Anomalies Detected',
    count: anomalyClusters.value.length
  }
])

const tabClusters = computed(() => {
  if (activeTab.value === 'similar') return similarClusters.value
  if (activeTab.value === 'new') return newClusters.value
  if (activeTab.value === 'observed') return observedClusters.value
  if (activeTab.value === 'anomaly') return filteredAnomalyClusters.value
  return knownClusters.value
})

const normalizedSearchQuery = computed(() => searchQuery.value.trim().toLowerCase())

const activeClusters = computed(() => {
  const query = normalizedSearchQuery.value
  if (!query) return tabClusters.value
  return tabClusters.value.filter((cluster) => clusterMatchesSearch(cluster, query))
})

const activeLogCount = computed(() =>
  activeClusters.value.reduce((total, cluster) => total + Number(cluster.count || 0), 0)
)

const pageCount = computed(() =>
  Math.max(1, Math.ceil(activeClusters.value.length / PAGE_SIZE))
)

const pagedClusters = computed(() => {
  const start = (currentPage.value - 1) * PAGE_SIZE
  return activeClusters.value.slice(start, start + PAGE_SIZE)
})

const pageSelectionState = computed<'all' | 'partial' | 'none'>(() => {
  const pageFingerprints = pagedClusters.value.map((cluster) => cluster.cluster)
  if (pageFingerprints.length === 0) return 'none'
  const selectedCount = pageFingerprints.filter((fp) =>
    selectedFingerprints.value.includes(fp)
  ).length
  if (selectedCount === pageFingerprints.length) return 'all'
  if (selectedCount > 0) return 'partial'
  return 'none'
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
    const available = new Set(props.clusters.map((cluster) => cluster.cluster))
    selectedFingerprints.value = selectedFingerprints.value.filter((fp) =>
      available.has(fp)
    )
  }
)

watch(activeTab, () => {
  currentPage.value = 1
  activeAnomalyTab.value = 'all'
})

watch(activeAnomalyTab, () => {
  currentPage.value = 1
})

watch(searchQuery, () => {
  currentPage.value = 1
})

watch(pageCount, (count) => {
  if (currentPage.value > count) currentPage.value = count
})

function similarity(item: Cluster): number {
  if (item.semantic_similarity && item.semantic_similarity > 0) {
    return item.semantic_similarity
  }
  if (item.similarity_score === null || item.similarity_score === undefined) {
    return 0
  }
  const score = Number(item.similarity_score)
  if (!Number.isFinite(score)) return 0
  return Math.round(score <= 1 ? score * 100 : score)
}

function formatCount(value: number): string {
  return new Intl.NumberFormat().format(value)
}

function percent(value: number): number {
  const score = Number(value)
  if (!Number.isFinite(score)) return 0
  return Math.round(score <= 1 ? score * 100 : score)
}

function clusterMatchesSearch(cluster: Cluster, query: string): boolean {
  return [
    cluster.cluster,
    cluster.message,
    cluster.stacktrace,
    cluster.log_level,
    statusLabel(cluster.pattern_status),
    cluster.pattern_status,
    cluster.anomaly_type,
    cluster.anomaly_reason
  ]
    .filter(Boolean)
    .some((value) => String(value).toLowerCase().includes(query))
}

function toggleFingerprint(fingerprint: string) {
  if (selectedFingerprints.value.includes(fingerprint)) {
    selectedFingerprints.value = selectedFingerprints.value.filter(
      (item) => item !== fingerprint
    )
    return
  }
  selectedFingerprints.value = [...selectedFingerprints.value, fingerprint]
}

function togglePageSelection() {
  const pageFingerprints = pagedClusters.value.map((cluster) => cluster.cluster)
  if (pageSelectionState.value === 'all') {
    selectedFingerprints.value = selectedFingerprints.value.filter(
      (fp) => !pageFingerprints.includes(fp)
    )
    return
  }
  selectedFingerprints.value = Array.from(
    new Set([...selectedFingerprints.value, ...pageFingerprints])
  )
}

function clearSelectedFingerprints() {
  selectedFingerprints.value = []
}

function requestManualMergeKnown() {
  emit('manual-merge-known', [...selectedFingerprints.value])
}

function canMergeSimilarMatch(match: Record<string, unknown>): boolean {
  const current = selectedSimilarCluster.value?.cluster
  const target = similarMatchFingerprint(match)
  return Boolean(current && target && target !== '-' && target !== current)
}

function requestMergeKnownForSimilarMatch(match: Record<string, unknown>) {
  const current = selectedSimilarCluster.value?.cluster
  const target = similarMatchFingerprint(match)
  if (!current || !target || target === '-' || target === current) return
  emit('manual-merge-known', [current, target])
}

defineExpose({ clearSelectedFingerprints })

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

function anomalyTypeLabel(item: Cluster): string {
  const type = item.anomaly_type || 'ANOMALY'
  const labels: Record<string, string> = {
    SPIKE: 'Pattern Increase',
    INCREASE: 'Pattern Increase',
    DROP: 'Pattern Decrease',
    DECREASE: 'Pattern Decrease',
    ABSENCE: 'Pattern Absence',
    NEW_ERROR: 'New Error Pattern',
    NEW_PATTERN: 'New Pattern',
    PRESENCE: 'New Pattern Presence',
    RECURRENCE: 'Pattern Recurrence',
    SIMILAR_CASE_MATCH: 'Similar Case Match'
  }
  return labels[type] ?? type
}

function anomalyTabFor(item: Cluster): AnomalyTab | 'other' {
  const type = (item.anomaly_type || '').toUpperCase()
  if (['DROP', 'DECREASE'].includes(type)) return 'decrease'
  if (['SPIKE', 'INCREASE'].includes(type)) return 'increase'
  if (type === 'ABSENCE') return 'absence'
  if (['RECURRENCE', 'RECUR', 'REOCCURRENCE'].includes(type)) return 'recurrence'
  return 'other'
}

function anomalyCountByTab(tab: AnomalyTab): number {
  return anomalyClusters.value.filter((cluster) => anomalyTabFor(cluster) === tab)
    .length
}

function anomalyReason(item: Cluster): string {
  if (item.anomaly_reason) return item.anomaly_reason
  const metric = item.anomaly_metric ?? {}
  const latest = metric.latest_count
  const baseline = metric.baseline_count
  if (latest !== undefined || baseline !== undefined) {
    return `latest=${latest ?? '-'}, baseline=${baseline ?? '-'}`
  }
  return ''
}

async function openSimilarCluster(item: Cluster) {
  selectedSimilarCluster.value = item
  similarError.value = ''
  if (item.similar_clusters?.length) return
  if (!props.serviceName) {
    similarError.value = 'Select a service before loading similar matches.'
    return
  }
  similarLoadingKey.value = item.cluster
  try {
    const { data } = await agentApi.similarPatternClusters(item.cluster, {
      service_name: props.serviceName,
      limit: 5
    })
    item.semantic_similarity = data.semantic_similarity
    item.similar_clusters = data.similar_clusters
  } catch (caught) {
    similarError.value = `Failed to load similar matches: ${(caught as Error).message}`
  } finally {
    similarLoadingKey.value = null
  }
}

function similarMatchKey(match: Record<string, unknown>, index: number): string {
  return `${similarMatchId(match)}-${index}`
}

function similarMatchId(match: Record<string, unknown>): string {
  return String(match.id ?? '-')
}

function similarMatchPercent(match: Record<string, unknown>): number {
  const value = Number(match.similarity ?? 0)
  return Math.round(value * 100)
}

function similarMatchMetadata(
  match: Record<string, unknown>,
  key: string
): string {
  const metadata = match.metadata as Record<string, unknown> | undefined
  return String(metadata?.[key] ?? '-')
}

function similarMatchFingerprint(match: Record<string, unknown>): string {
  const metadata = match.metadata as Record<string, unknown> | undefined
  return String(metadata?.fingerprint ?? match.id ?? '-')
}

function similarMatchDocument(match: Record<string, unknown>): string {
  return String(match.document ?? '-')
}
</script>
