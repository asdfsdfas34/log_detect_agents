<template>
  <div class="grid gap-4 rounded-xl border bg-white p-4 shadow-sm lg:grid-cols-2">
    <VChart class="h-64" :option="gaugeOption" autoresize />
    <VChart class="h-64" :option="barOption" autoresize />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, GaugeChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'

use([CanvasRenderer, GaugeChart, BarChart, GridComponent, TooltipComponent])

const props = defineProps<{
  score: number
  metrics: { error_rate: number | null; latency_p95: number | null; rps: number | null }
}>()

const gaugeOption = computed(() => ({
  series: [
    {
      type: 'gauge',
      min: 0,
      max: 100,
      detail: { valueAnimation: true, formatter: '{value}' },
      data: [{ value: props.score, name: 'Impact' }]
    }
  ]
}))

const barOption = computed(() => ({
  xAxis: { type: 'category', data: ['Frequency', 'Timing', 'Traffic'] },
  yAxis: { type: 'value', max: 100 },
  series: [
    {
      type: 'bar',
      data: [
        Math.round((props.metrics.error_rate ?? 0) * 100),
        Math.min(100, Math.round((props.metrics.latency_p95 ?? 0) / 3)),
        Math.max(0, Math.min(100, Math.round(props.metrics.rps ?? 0)))
      ],
      itemStyle: { color: '#2563eb' }
    }
  ]
}))
</script>
