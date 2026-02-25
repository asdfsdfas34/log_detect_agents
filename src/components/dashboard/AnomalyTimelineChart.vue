<template>
  <div class="rounded-xl border bg-white p-4 shadow-sm">
    <h3 class="mb-3 text-lg font-semibold">Anomaly Timeline</h3>
    <VChart class="h-72" :option="option" autoresize />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import type { Anomaly, NormalizedLog } from '@/types/agentTypes'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

const props = defineProps<{ anomalies: Anomaly[]; logs: NormalizedLog[] }>()

const option = computed(() => {
  const points = props.logs
    .filter((log) => !!log.timestamp)
    .map((log) => ({
      time: log.timestamp as string,
      value: props.anomalies.filter((a) => a.system === log.system).length
    }))

  return {
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: points.map((p) => p.time) },
    yAxis: { type: 'value' },
    series: [{ type: 'line', data: points.map((p) => p.value), smooth: true }]
  }
})
</script>
