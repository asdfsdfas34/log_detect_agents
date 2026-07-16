<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="mb-3 flex items-center justify-between">
      <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">
        프로세스 맵
      </p>
      <button
        v-if="activeComponent"
        type="button"
        class="text-xs font-medium text-blue-600 hover:text-blue-700"
        @click="emit('clear')"
      >
        필터 해제
      </button>
    </div>

    <div class="space-y-3">
      <div v-for="lane in lanes" :key="lane" class="flex flex-col gap-1">
        <p class="text-[10px] font-semibold uppercase tracking-wide text-slate-400">
          {{ lane }}
        </p>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="node in nodesByLane(lane)"
            :key="node.id"
            type="button"
            class="flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-xs font-medium transition"
            :class="nodeClass(node)"
            @click="emit('select', node.components, node.label)"
          >
            <span
              class="inline-block h-2 w-2 rounded-full"
              :class="dotClass(state(node))"
              aria-hidden="true"
            />
            <span>{{ node.label }}</span>
            <span class="text-[10px] text-slate-400">{{ stateLabel(state(node)) }}</span>
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentTraceEvent } from '@/types/agentTypes'
import {
  PROCESS_MAP_NODES,
  type ProcessMapNode,
  type ProcessNodeState,
  processNodeState
} from '@/components/observability/observability'

const props = defineProps<{
  events: AgentTraceEvent[]
  activeComponent: string | null
}>()

const emit = defineEmits<{
  (event: 'select', components: string[], label: string): void
  (event: 'clear'): void
}>()

const lanes = computed(() => {
  const seen: string[] = []
  for (const node of PROCESS_MAP_NODES) {
    if (!seen.includes(node.lane)) seen.push(node.lane)
  }
  return seen
})

function nodesByLane(lane: string): ProcessMapNode[] {
  return PROCESS_MAP_NODES.filter((node) => node.lane === lane)
}

function state(node: ProcessMapNode): ProcessNodeState {
  return processNodeState(node, props.events)
}

function stateLabel(value: ProcessNodeState): string {
  return { idle: '미실행', running: '실행 중', completed: '완료', failed: '실패' }[value]
}

function dotClass(value: ProcessNodeState): string {
  return {
    idle: 'bg-slate-300',
    running: 'bg-blue-500 animate-pulse',
    completed: 'bg-emerald-500',
    failed: 'bg-red-500'
  }[value]
}

function nodeClass(node: ProcessMapNode): string {
  const isActive = node.components.some((component) => component === props.activeComponent)
  if (isActive) return 'border-blue-500 bg-blue-50 text-blue-700'
  const value = state(node)
  if (value === 'failed') return 'border-red-200 bg-red-50 text-red-700'
  if (value === 'running') return 'border-blue-200 bg-white text-slate-700'
  if (value === 'completed') return 'border-emerald-200 bg-white text-slate-700'
  return 'border-slate-200 bg-slate-50 text-slate-400'
}
</script>
