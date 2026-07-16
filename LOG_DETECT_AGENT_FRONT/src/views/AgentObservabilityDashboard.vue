<template>
  <AppLayout>
    <template #header-right>
      <RouterLink
        to="/"
        class="rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-600 hover:bg-slate-50"
      >
        분석 대시보드로
      </RouterLink>
    </template>

    <ObservabilitySummaryHeader
      :run="run"
      :runs="observability.runList"
      :metrics="metrics"
      @select-run="observability.selectRun"
    />

    <ProcessMap
      :events="events"
      :active-component="componentFilter"
      @select="onComponentFilter"
      @clear="clearComponentFilter"
    />

    <TraceFilterBar
      v-model:search-text="filters.searchText"
      v-model:selected-kind="filters.kind"
      v-model:selected-status="filters.status"
      v-model:selected-agent="filters.agent"
      v-model:selected-dep="filters.dep"
      v-model:failures-only="filters.failuresOnly"
      :agents="agents"
      @reset="resetFilters"
    />

    <div class="grid grid-cols-1 gap-4 lg:grid-cols-3">
      <div class="lg:col-span-2">
        <ProcessTimeline
          v-model:auto-scroll="autoScroll"
          v-model:paused="paused"
          :nodes="visibleNodes"
          :selected-event-id="observability.selectedEventId"
          :empty-label="emptyLabel"
          @select="observability.selectEvent"
        />
      </div>

      <!-- Wide screens: inline detail panel. -->
      <div class="hidden lg:block">
        <TraceEventDetailPanel
          :event="observability.selectedEvent"
          :show-close="false"
        />
      </div>
    </div>

    <!-- Narrow screens: detail panel becomes a bottom drawer. -->
    <div
      v-if="observability.selectedEvent && isNarrow"
      class="fixed inset-x-0 bottom-0 z-40 max-h-[80vh] rounded-t-xl border-t border-slate-200 bg-white p-3 shadow-2xl lg:hidden"
    >
      <TraceEventDetailPanel
        :event="observability.selectedEvent"
        :show-close="true"
        @close="observability.selectEvent(null)"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { RouterLink } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import ObservabilitySummaryHeader from '@/components/observability/ObservabilitySummaryHeader.vue'
import ProcessMap from '@/components/observability/ProcessMap.vue'
import ProcessTimeline from '@/components/observability/ProcessTimeline.vue'
import TraceEventDetailPanel from '@/components/observability/TraceEventDetailPanel.vue'
import TraceFilterBar from '@/components/observability/TraceFilterBar.vue'
import {
  DEPENDENCY_FILTERS,
  collapseBySpan
} from '@/components/observability/observability'
import { useObservabilityStore } from '@/stores/observabilityStore'
import type { AgentTraceEvent } from '@/types/agentTypes'

const observability = useObservabilityStore()

const autoScroll = ref(true)
const paused = ref(false)
const componentFilter = ref<string | null>(null)
const isNarrow = ref(false)

const filters = reactive({
  searchText: '',
  kind: 'all',
  status: 'all',
  agent: 'all',
  dep: 'all',
  failuresOnly: false
})

const run = computed(() => observability.selectedRun)
const events = computed<AgentTraceEvent[]>(() => run.value?.events ?? [])

const agents = computed(() => {
  const set = new Set<string>()
  for (const event of events.value) set.add(event.agent_name)
  return Array.from(set).sort()
})

const metrics = computed(() => {
  const list = events.value
  const agentSet = new Set<string>()
  let tools = 0
  let retries = 0
  let failedValidators = 0
  for (const event of list) {
    if (event.kind === 'agent') agentSet.add(event.agent_name)
    if (event.kind === 'tool_call' && event.event_type === 'tool.started') tools += 1
    if (event.event_type === 'agent.retrying') retries += 1
    if (event.event_type === 'validator.failed') failedValidators += 1
  }
  return {
    agents: agentSet.size,
    tools,
    retries,
    failedValidators,
    total: list.length
  }
})

const filteredEvents = computed<AgentTraceEvent[]>(() => {
  const search = filters.searchText.trim().toLowerCase()
  const depComponents =
    filters.dep === 'all'
      ? null
      : DEPENDENCY_FILTERS.find((item) => item.value === filters.dep)?.components ?? null
  return events.value.filter((event) => {
    if (filters.kind !== 'all' && event.kind !== filters.kind) return false
    if (filters.status !== 'all' && event.status !== filters.status) return false
    if (filters.agent !== 'all' && event.agent_name !== filters.agent) return false
    if (componentFilter.value && event.component !== componentFilter.value) return false
    if (depComponents && !depComponents.includes(event.component)) return false
    if (
      filters.failuresOnly &&
      event.status !== 'failed' &&
      event.event_type !== 'agent.retrying' &&
      !event.fallback_used
    ) {
      return false
    }
    if (search) {
      const haystack = [
        event.title,
        event.summary,
        event.agent_name,
        event.request_id,
        event.metadata?.tool_name,
        ...event.evidence_refs
      ]
        .filter((value): value is string => typeof value === 'string')
        .join(' ')
        .toLowerCase()
      if (!haystack.includes(search)) return false
    }
    return true
  })
})

const visibleNodes = computed(() => collapseBySpan(filteredEvents.value))

const emptyLabel = computed(() => {
  if (!run.value) return '아직 실행된 분석이 없습니다. 분석 대시보드에서 분석을 실행하세요.'
  if (events.value.length === 0) return '이벤트 수신 대기 중입니다.'
  return '현재 필터에 해당하는 이벤트가 없습니다.'
})

function onComponentFilter(components: string[]) {
  componentFilter.value = components[0] ?? null
}

function clearComponentFilter() {
  componentFilter.value = null
}

function resetFilters() {
  filters.searchText = ''
  filters.kind = 'all'
  filters.status = 'all'
  filters.agent = 'all'
  filters.dep = 'all'
  filters.failuresOnly = false
  componentFilter.value = null
}

function updateViewport() {
  isNarrow.value = window.innerWidth < 1024
}

onMounted(() => {
  updateViewport()
  window.addEventListener('resize', updateViewport)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', updateViewport)
})
</script>
