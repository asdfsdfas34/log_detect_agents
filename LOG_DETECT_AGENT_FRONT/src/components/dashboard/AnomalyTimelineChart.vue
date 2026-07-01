<template>
  <div class="rounded-xl border bg-white p-4 shadow-sm">
    <h3 class="mb-3 text-lg font-semibold">Anomaly Timeline</h3>
    <VChart class="h-36" :option="option" autoresize />
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import VChart from 'vue-echarts'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import type {
  Anomaly,
  AnomalyDailyCount,
  NormalizedLog
} from '@/types/agentTypes'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent])

const props = defineProps<{
  anomalies: Anomaly[]
  dailyCounts?: AnomalyDailyCount[]
  logs: NormalizedLog[]
}>()

const option = computed(() => {
  const persistedPoints =
    props.dailyCounts
      ?.filter((item) => !!item.analysis_date)
      .map((item) => ({
        time: item.analysis_date,
        value: item.anomaly_count
      }))
      .sort((a, b) => a.time.localeCompare(b.time)) ?? []

  if (persistedPoints.length > 0) {
    return chartOption(persistedPoints)
  }

  const dailyCounts = new Map<string, number>()

  for (const log of props.logs) {
    const day = dateKey(log.timestamp)
    if (day) dailyCounts.set(day, dailyCounts.get(day) ?? 0)
  }

  const anomalyDates = props.anomalies
    .map((anomaly) => dateKey(anomaly.timestamp))
    .filter((day): day is string => !!day)

  if (anomalyDates.length > 0) {
    for (const day of anomalyDates) {
      dailyCounts.set(day, (dailyCounts.get(day) ?? 0) + 1)
    }
  } else {
    for (const log of props.logs) {
      const day = dateKey(log.timestamp)
      if (!day || !matchesAnomaly(log)) continue
      dailyCounts.set(day, (dailyCounts.get(day) ?? 0) + 1)
    }
  }

  const points = [...dailyCounts.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([time, value]) => ({ time, value }))

  return chartOption(points)
})

function chartOption(points: Array<{ time: string; value: number }>) {
  return {
    tooltip: { trigger: 'axis' },
    grid: { left: 44, right: 16, top: 12, bottom: 28, containLabel: true },
    xAxis: {
      type: 'category',
      data: points.map((p) => p.time),
      axisLabel: { hideOverlap: true, interval: 'auto' }
    },
    yAxis: {
      type: 'value',
      min: 0,
      minInterval: 1,
      splitNumber: 2,
      axisLabel: {
        margin: 8,
        formatter: (value: number) => `${Math.round(value)}`
      }
    },
    series: [{ type: 'line', data: points.map((p) => p.value), smooth: true }]
  }
}

function dateKey(value?: string): string {
  if (!value) return ''
  return value.slice(0, 10)
}

function matchesAnomaly(log: NormalizedLog): boolean {
  const level = log.level?.toUpperCase()
  if (!['ERROR', 'WARN', 'WARNING'].includes(level ?? '')) return false
  return props.anomalies.some((anomaly) => {
    if (anomaly.system && anomaly.system !== log.system) return false
    if (!anomaly.message && !anomaly.pattern) return true
    return (
      (!!anomaly.message && anomaly.message === log.message) ||
      (!!anomaly.pattern && !!log.message?.includes(anomaly.pattern))
    )
  })
}
</script>
