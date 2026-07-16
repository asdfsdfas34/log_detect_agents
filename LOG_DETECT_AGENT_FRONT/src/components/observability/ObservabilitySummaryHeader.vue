<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">
          Agent Process Observability
        </p>
        <div class="mt-1 flex flex-wrap items-center gap-2">
          <select
            class="rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-800"
            :value="run?.stream_id ?? ''"
            :disabled="runs.length === 0"
            @change="onSelect(($event.target as HTMLSelectElement).value)"
          >
            <option v-if="runs.length === 0" value="">실행 없음</option>
            <option v-for="item in runs" :key="item.stream_id" :value="item.stream_id">
              {{ runOptionLabel(item) }}
            </option>
          </select>
          <span
            v-if="run"
            class="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold"
            :class="runStatus.chip"
          >
            <span aria-hidden="true">{{ runStatus.icon }}</span>{{ runStatus.label }}
          </span>
          <span
            v-if="run"
            class="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-semibold"
            :class="connection.chip"
          >
            <span aria-hidden="true">{{ connection.icon }}</span>{{ connection.label }}
          </span>
        </div>
        <p v-if="run" class="mt-1 text-xs text-slate-500">
          <span
            class="mr-1 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold"
            :class="run.operation === 'recommendation' ? 'bg-rose-100 text-rose-700' : 'bg-blue-100 text-blue-700'"
          >
            {{ run.operation === 'recommendation' ? '추천 생성' : '전체 분석' }}
          </span>
          {{ run.service_name || '서비스 미지정' }} ·
          기준일 {{ run.analysis_date || '—' }} ·
          <template v-if="run.fingerprint">fp {{ run.fingerprint.slice(0, 12) }} · </template>
          request {{ run.request_id ? run.request_id.slice(0, 8) : '—' }}
        </p>
      </div>

      <dl v-if="run" class="grid grid-cols-3 gap-2 text-center sm:grid-cols-6">
        <div class="rounded bg-slate-50 px-2 py-1">
          <dt class="text-[10px] uppercase text-slate-400">소요</dt>
          <dd class="text-sm font-semibold text-slate-800">{{ elapsed }}</dd>
        </div>
        <div class="rounded bg-slate-50 px-2 py-1">
          <dt class="text-[10px] uppercase text-slate-400">Agent</dt>
          <dd class="text-sm font-semibold text-slate-800">{{ metrics.agents }}</dd>
        </div>
        <div class="rounded bg-slate-50 px-2 py-1">
          <dt class="text-[10px] uppercase text-slate-400">Tool Call</dt>
          <dd class="text-sm font-semibold text-slate-800">{{ metrics.tools }}</dd>
        </div>
        <div class="rounded bg-slate-50 px-2 py-1">
          <dt class="text-[10px] uppercase text-slate-400">재시도</dt>
          <dd class="text-sm font-semibold text-slate-800">{{ metrics.retries }}</dd>
        </div>
        <div class="rounded bg-slate-50 px-2 py-1">
          <dt class="text-[10px] uppercase text-slate-400">검증 실패</dt>
          <dd
            class="text-sm font-semibold"
            :class="metrics.failedValidators > 0 ? 'text-red-600' : 'text-slate-800'"
          >
            {{ metrics.failedValidators }}
          </dd>
        </div>
        <div class="rounded bg-slate-50 px-2 py-1">
          <dt class="text-[10px] uppercase text-slate-400">이벤트</dt>
          <dd class="text-sm font-semibold text-slate-800">{{ metrics.total }}</dd>
        </div>
      </dl>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ObservabilityRun } from '@/types/agentTypes'
import {
  connectionMeta,
  elapsedSince,
  runStatusMeta
} from '@/components/observability/observability'

const props = defineProps<{
  run: ObservabilityRun | null
  runs: ObservabilityRun[]
  metrics: {
    agents: number
    tools: number
    retries: number
    failedValidators: number
    total: number
  }
}>()

const emit = defineEmits<{ (event: 'select-run', streamId: string): void }>()

const runStatus = computed(() =>
  runStatusMeta(props.run?.status ?? 'running')
)
const connection = computed(() =>
  connectionMeta(props.run?.connection ?? 'idle')
)

const elapsed = computed(() => {
  if (!props.run) return '—'
  return elapsedSince(props.run.started_at, props.run.ended_at ?? new Date().toISOString())
})

function runOptionLabel(run: ObservabilityRun): string {
  const time = new Date(run.started_at).toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
  const kind = run.operation === 'recommendation' ? '추천' : '분석'
  const fp = run.fingerprint ? ` · ${run.fingerprint.slice(0, 8)}` : ''
  return `[${kind}] ${run.service_name || '서비스'}${fp} · ${time}`
}

function onSelect(streamId: string) {
  if (streamId) emit('select-run', streamId)
}
</script>
