<template>
  <div class="rounded-xl border bg-white p-4 shadow-sm">
    <div class="mb-3 flex items-center justify-between">
      <h3 class="text-lg font-semibold">Pattern Clusters</h3>
      <p class="text-xs text-slate-500">Click a pattern to rerun recommendations</p>
    </div>
    <div class="overflow-x-auto">
      <table class="min-w-full text-left text-sm">
        <thead class="text-xs uppercase text-slate-500">
          <tr>
            <th class="py-2">Cluster</th>
            <th class="py-2">Error Message</th>
            <th class="py-2">Level</th>
            <th class="py-2">Count</th>
            <th class="py-2">Similarity</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in sortedClusters"
            :key="item.cluster"
            class="cursor-pointer border-t hover:bg-blue-50"
            @click="emit('selectCluster', item)"
          >
            <td class="py-2 font-mono text-xs" :class="isErrorLevel(item) ? 'font-semibold text-red-600' : ''">
              {{ item.cluster }}
            </td>
            <td class="max-w-xl py-2 text-slate-700">
              {{ item.message ?? 'No message captured for this pattern' }}
            </td>
            <td class="py-2">
              <span class="rounded px-2 py-1 text-xs font-semibold" :class="levelClass(item.log_level)">
                {{ item.log_level ?? '-' }}
              </span>
            </td>
            <td class="py-2">{{ item.count }}</td>
            <td class="py-2">{{ similarity(item.count) }}%</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { Cluster } from '@/types/agentTypes'

const props = defineProps<{ clusters: Cluster[] }>()
const emit = defineEmits<{ selectCluster: [cluster: Cluster] }>()

const sortedClusters = computed(() => [...props.clusters].sort((a, b) => b.count - a.count))
const total = computed(() => props.clusters.reduce((sum, item) => sum + item.count, 0) || 1)

function similarity(count: number): number {
  return Math.round((count / total.value) * 100)
}

// Highlight error-level fingerprints so operators can scan critical patterns quickly.
function isErrorLevel(item: Cluster): boolean {
  return item.log_level === 'ERROR'
}

// Map log levels to compact badge styles in the Pattern Clusters table.
function levelClass(level?: string): string {
  if (level === 'ERROR') return 'bg-red-100 text-red-700'
  if (level === 'WARN') return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-600'
}
</script>
