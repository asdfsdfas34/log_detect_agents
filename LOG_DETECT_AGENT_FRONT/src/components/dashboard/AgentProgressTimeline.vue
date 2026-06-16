<template>
  <div
    class="rounded-xl border bg-white shadow-sm"
    :class="compact ? 'p-3' : 'p-4'"
  >
    <h3
      :class="
        compact ? 'mb-2 text-sm font-semibold' : 'mb-3 text-lg font-semibold'
      "
    >
      Agent Execution Timeline
    </h3>
    <ol :class="compact ? 'space-y-2' : 'space-y-3'">
      <li
        v-for="step in steps"
        :key="step.name"
        class="flex items-center gap-2"
      >
        <span
          :class="[
            compact ? 'h-2.5 w-2.5' : 'h-3 w-3',
            'shrink-0 rounded-full',
            statusColor(step.status)
          ]"
        />
        <span
          class="min-w-0 flex-1 truncate font-medium"
          :class="compact ? 'text-xs' : 'text-sm'"
        >
          {{ step.name }}
        </span>
        <span
          class="shrink-0 uppercase text-slate-500"
          :class="compact ? 'text-[10px]' : 'text-xs'"
        >
          {{ step.status }}
        </span>
      </li>
    </ol>
  </div>
</template>

<script setup lang="ts">
import type { AgentStepStatus } from '@/types/agentTypes'

withDefaults(defineProps<{ steps: AgentStepStatus[]; compact?: boolean }>(), {
  compact: false
})

function statusColor(status: AgentStepStatus['status']): string {
  if (status === 'completed') return 'bg-green-500'
  if (status === 'running') return 'animate-pulse bg-blue-500'
  if (status === 'failed') return 'bg-red-500'
  if (status === 'skipped') return 'bg-amber-500'
  return 'bg-slate-300'
}
</script>
