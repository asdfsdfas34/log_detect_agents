<template>
  <section class="flex h-full flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
    <div class="flex items-center justify-between border-b border-slate-100 px-4 py-2">
      <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">
        전체 프로세스 타임라인
        <span class="ml-1 font-normal text-slate-400">({{ nodes.length }})</span>
      </p>
      <div class="flex items-center gap-2 text-xs">
        <button
          type="button"
          class="rounded border px-2 py-0.5"
          :class="autoScroll ? 'border-blue-300 bg-blue-50 text-blue-700' : 'border-slate-300 text-slate-500'"
          @click="emit('update:autoScroll', !autoScroll)"
        >
          자동 스크롤 {{ autoScroll ? 'ON' : 'OFF' }}
        </button>
        <button
          type="button"
          class="rounded border px-2 py-0.5"
          :class="paused ? 'border-amber-300 bg-amber-50 text-amber-700' : 'border-slate-300 text-slate-500'"
          @click="emit('update:paused', !paused)"
        >
          {{ paused ? '일시정지' : '실시간' }}
        </button>
      </div>
    </div>

    <div
      v-if="nodes.length === 0"
      class="flex flex-1 items-center justify-center py-12 text-center text-sm text-slate-400"
    >
      {{ emptyLabel }}
    </div>

    <ol
      v-else
      ref="scrollRef"
      class="flex-1 space-y-1 overflow-y-auto px-2 py-2"
      style="max-height: 62vh"
    >
      <li
        v-for="node in nodes"
        :key="node.id"
        class="cursor-pointer rounded border px-2 py-1.5 transition"
        :class="rowClass(node)"
        :style="{ marginLeft: `${indent(node) * 16}px` }"
        @click="emit('select', node.representativeEventId)"
      >
        <div class="flex items-center gap-2">
          <span
            class="inline-block h-2 w-2 shrink-0 rounded-full"
            :class="kindMeta(node.kind).dot"
            aria-hidden="true"
          />
          <span
            class="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase"
            :class="kindMeta(node.kind).chip"
          >
            <span aria-hidden="true">{{ kindMeta(node.kind).icon }}</span>
            {{ kindMeta(node.kind).label }}
          </span>
          <span class="min-w-0 flex-1 truncate text-sm font-medium text-slate-800">
            {{ node.title }}
          </span>
          <span
            class="inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase"
            :class="statusMeta(node.status).chip"
          >
            <span aria-hidden="true">{{ statusMeta(node.status).icon }}</span>
            {{ statusMeta(node.status).label }}
          </span>
        </div>
        <div class="mt-0.5 flex items-center gap-2 pl-4 text-[10px] text-slate-400">
          <span>{{ formatClock(node.startedAt) }}</span>
          <span>·</span>
          <span>{{ node.agentName }}</span>
          <span v-if="node.durationMs != null">· {{ formatDuration(node.durationMs) }}</span>
          <span v-if="node.attempt != null && node.maxAttempts != null">
            · 시도 {{ node.attempt }}/{{ node.maxAttempts }}
          </span>
          <span v-if="node.fallbackUsed" class="font-semibold text-orange-500">· fallback</span>
        </div>
      </li>
    </ol>
  </section>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import {
  formatClock,
  formatDuration,
  kindMeta,
  statusMeta,
  type TimelineNode
} from '@/components/observability/observability'

const props = defineProps<{
  nodes: TimelineNode[]
  selectedEventId: string | null
  autoScroll: boolean
  paused: boolean
  emptyLabel: string
}>()

const emit = defineEmits<{
  (event: 'select', eventId: string): void
  (event: 'update:autoScroll', value: boolean): void
  (event: 'update:paused', value: boolean): void
}>()

const scrollRef = ref<HTMLElement | null>(null)

function indent(node: TimelineNode): number {
  return kindMeta(node.kind).indent
}

function rowClass(node: TimelineNode): string {
  const selected = node.representativeEventId === props.selectedEventId
  if (selected) return 'border-blue-400 bg-blue-50'
  if (node.hasError || node.status === 'failed') return 'border-red-100 bg-red-50/40 hover:bg-red-50'
  return 'border-slate-100 bg-white hover:bg-slate-50'
}

watch(
  () => props.nodes.length,
  async () => {
    if (!props.autoScroll || props.paused) return
    await nextTick()
    const element = scrollRef.value
    if (element) element.scrollTop = element.scrollHeight
  }
)
</script>
