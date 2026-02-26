<template>
  <div class="rounded-xl border bg-white p-4 shadow-sm">
    <h3 class="mb-3 text-lg font-semibold">Pattern Clusters</h3>
    <div class="overflow-x-auto">
      <table class="min-w-full text-left text-sm">
        <thead class="text-xs uppercase text-slate-500">
          <tr>
            <th class="py-2">Cluster</th>
            <th class="py-2">Count</th>
            <th class="py-2">Similarity</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in sortedClusters" :key="item.cluster" class="border-t">
            <td class="py-2" :class="item.cluster.includes('error') ? 'font-semibold text-red-600' : ''">
              {{ item.cluster }}
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

const sortedClusters = computed(() => [...props.clusters].sort((a, b) => b.count - a.count))
const total = computed(() => props.clusters.reduce((sum, item) => sum + item.count, 0) || 1)

function similarity(count: number): number {
  return Math.round((count / total.value) * 100)
}
</script>
