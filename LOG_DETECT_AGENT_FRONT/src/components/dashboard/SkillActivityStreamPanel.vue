<template>
  <section class="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
    <div class="mb-3">
      <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Skill Activity Stream
      </p>
      <div class="mt-2 rounded border border-blue-100 bg-blue-50 p-2">
        <div class="flex items-center justify-between gap-2">
          <p class="text-sm font-semibold text-slate-800">
            {{ current?.skill ?? '대기중' }}
          </p>
          <span
            class="shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold uppercase"
            :class="statusClass(current?.status ?? executionStatus)"
          >
            {{ current?.status ?? executionStatus }}
          </span>
        </div>
        <p class="mt-1 text-[11px] leading-4 text-slate-600">
          {{ current?.action ?? '아직 실행중인 backend skill이 없습니다.' }}
        </p>
      </div>
    </div>

    <div
      v-if="items.length === 0"
      class="py-6 text-center text-xs text-slate-400"
    >
      실행 stream이 아직 없습니다.
    </div>
    <ol v-else class="max-h-[70vh] space-y-2 overflow-y-auto pr-1">
      <li
        v-for="item in items"
        :key="item.id"
        class="rounded border border-slate-100 bg-slate-50 p-2 text-xs"
      >
        <div class="flex items-start justify-between gap-2">
          <div class="min-w-0">
            <p class="truncate font-semibold text-slate-700">
              {{ item.skill }}
            </p>
            <p v-if="item.agent" class="mt-0.5 text-[11px] text-slate-400">
              {{ item.agent }}
            </p>
          </div>
          <span
            class="shrink-0 rounded px-2 py-0.5 text-[10px] font-semibold uppercase"
            :class="statusClass(item.status)"
          >
            {{ item.status }}
          </span>
        </div>
        <p class="mt-1 text-[11px] leading-4 text-slate-600">
          {{ item.action }}
        </p>
        <p
          v-if="item.detail"
          class="mt-1 line-clamp-2 text-[11px] leading-4 text-slate-400"
        >
          {{ item.detail }}
        </p>
        <div class="mt-2 flex items-center justify-between text-[10px] text-slate-400">
          <span>{{ item.source }}</span>
          <time>{{ formatTime(item.at) }}</time>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import type { SkillActivityStreamItem } from '@/types/agentTypes'

defineProps<{
  items: SkillActivityStreamItem[]
  current: SkillActivityStreamItem | null
  executionStatus: string
}>()

function statusClass(status: string): string {
  if (status === 'completed' || status === 'success') {
    return 'bg-emerald-100 text-emerald-700'
  }
  if (status === 'running' || status === 'started' || status === 'selected') {
    return 'bg-blue-100 text-blue-700'
  }
  if (status === 'planned' || status === 'pending') {
    return 'bg-amber-100 text-amber-700'
  }
  if (status === 'failed' || status === 'error') {
    return 'bg-red-100 text-red-700'
  }
  if (status === 'skipped') return 'bg-slate-200 text-slate-600'
  return 'bg-slate-100 text-slate-600'
}

function formatTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  return date.toLocaleTimeString('ko-KR', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  })
}
</script>
