<template>
  <section class="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
    <div class="mb-3 flex items-center justify-between gap-2">
      <div>
        <h2 class="text-xs font-semibold uppercase tracking-wide text-slate-500">
          LangSmith Trace
        </h2>
        <p class="mt-1 text-[11px] text-slate-400">
          {{ status.project }} · {{ status.source }}
        </p>
      </div>
      <button
        class="rounded border border-slate-300 px-2 py-1 text-[11px] text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="loading"
        @click="$emit('refresh')"
      >
        {{ loading ? '조회중' : '새로고침' }}
      </button>
    </div>

    <p
      v-if="!status.enabled"
      class="mb-2 rounded bg-amber-50 px-2 py-1 text-[11px] text-amber-700"
    >
      LANGSMITH_TRACING이 꺼져 있어 로컬 agent flow 로그를 표시합니다.
    </p>
    <p
      v-else-if="status.error"
      class="mb-2 rounded bg-red-50 px-2 py-1 text-[11px] text-red-700"
    >
      LangSmith 조회 실패: {{ status.error }}
    </p>

    <div v-if="runs.length === 0" class="py-6 text-center text-xs text-slate-400">
      표시할 LangSmith 로그가 없습니다.
    </div>
    <ol v-else class="max-h-[70vh] space-y-2 overflow-y-auto pr-1">
      <li
        v-for="run in runs"
        :key="run.id"
        class="rounded border border-slate-100 bg-slate-50 p-2 text-xs"
      >
        <div class="flex items-center justify-between gap-2">
          <span class="font-semibold text-slate-700">{{ run.name }}</span>
          <span
            class="rounded px-2 py-0.5 text-[10px] font-semibold uppercase"
            :class="statusClass(run.status)"
          >
            {{ run.status }}
          </span>
        </div>
        <div class="mt-1 space-y-0.5 text-[11px] text-slate-500">
          <p>{{ run.run_type || 'chain' }} · {{ run.elapsed_ms ?? '-' }}ms</p>
          <p v-if="run.request_id" class="font-mono">req {{ run.request_id }}</p>
          <p>{{ run.start_time || '-' }}</p>
          <p v-if="run.error" class="text-red-600">{{ run.error }}</p>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import type { LangSmithRunItem } from '@/types/agentTypes'

defineProps<{
  runs: LangSmithRunItem[]
  loading: boolean
  status: {
    enabled: boolean
    project: string
    source: string
    error?: string | null
  }
}>()

defineEmits<{ refresh: [] }>()

function statusClass(status: string): string {
  if (status === 'completed' || status === 'success') return 'bg-emerald-100 text-emerald-700'
  if (status === 'started' || status === 'retrying') return 'bg-blue-100 text-blue-700'
  if (status === 'failed' || status === 'error') return 'bg-red-100 text-red-700'
  return 'bg-slate-200 text-slate-600'
}
</script>
