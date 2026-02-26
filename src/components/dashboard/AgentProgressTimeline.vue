<template>
  <div class="rounded-xl border bg-white p-4 shadow-sm">
    <h3 class="mb-3 text-lg font-semibold">Agent Execution Timeline</h3>
    <ol class="space-y-3">
      <li v-for="step in steps" :key="step.name" class="flex items-center gap-3">
        <span class="h-3 w-3 rounded-full" :class="statusColor(step.status)" />
        <span class="text-sm font-medium">{{ step.name }}</span>
        <span class="text-xs uppercase text-slate-500">{{ step.status }}</span>
      </li>
    </ol>
  </div>
</template>

<script setup lang="ts">
import type { AgentStepStatus } from '@/types/agentTypes'

defineProps<{ steps: AgentStepStatus[] }>()

function statusColor(status: AgentStepStatus['status']): string {
  if (status === 'completed') return 'bg-green-500'
  if (status === 'running') return 'bg-blue-500 animate-pulse'
  if (status === 'failed') return 'bg-red-500'
  if (status === 'skipped') return 'bg-amber-500'
  return 'bg-slate-300'
}
</script>
