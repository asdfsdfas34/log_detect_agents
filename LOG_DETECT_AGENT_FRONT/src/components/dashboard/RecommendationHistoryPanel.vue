<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="mb-4 flex items-center justify-between gap-3">
      <div>
        <h2
          class="text-sm font-semibold uppercase tracking-wide text-slate-500"
        >
          Saved Recommendations
        </h2>
        <p class="mt-1 text-xs text-slate-500">
          SQLite에 저장된 Recommendation 결과를 최신순으로 조회합니다.
        </p>
      </div>
      <button
        class="rounded border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100"
        :disabled="loading"
        @click="$emit('refresh')"
      >
        {{ loading ? '조회중...' : '새로고침' }}
      </button>
    </div>

    <div v-if="loading" class="py-6 text-center text-sm text-slate-500">
      저장된 Recommendation을 조회중입니다...
    </div>
    <div
      v-else-if="items.length === 0"
      class="py-6 text-center text-sm text-slate-500"
    >
      저장된 Recommendation이 없습니다.
    </div>
    <div v-else class="overflow-hidden rounded border border-slate-200">
      <table class="min-w-full divide-y divide-slate-200 text-left text-sm">
        <thead
          class="bg-slate-50 text-xs uppercase tracking-wide text-slate-500"
        >
          <tr>
            <th class="px-3 py-2">ID</th>
            <th class="px-3 py-2">Service</th>
            <th class="px-3 py-2">Risk</th>
            <th class="px-3 py-2">Recommendation</th>
            <th class="px-3 py-2">Created</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100 bg-white">
          <tr
            v-for="item in items"
            :key="item.id"
            class="align-top hover:bg-slate-50"
          >
            <td
              class="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-500"
            >
              #{{ item.id }}
            </td>
            <td class="whitespace-nowrap px-3 py-2 font-medium text-slate-700">
              {{ item.service_name }}
            </td>
            <td class="whitespace-nowrap px-3 py-2 text-slate-600">
              <span class="font-semibold">{{ item.risk_score ?? '-' }}</span>
              <span class="ml-1 text-xs text-slate-400">{{
                item.confidence ?? ''
              }}</span>
            </td>
            <td class="px-3 py-2 text-slate-700">
              <p class="font-medium text-slate-800">
                {{ item.executive_summary || '-' }}
              </p>
              <p class="mt-1 line-clamp-2 text-xs text-slate-500">
                {{ item.recommendation || '-' }}
              </p>
            </td>
            <td class="whitespace-nowrap px-3 py-2 text-xs text-slate-500">
              {{ item.created_at }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup lang="ts">
import type { RecommendationHistoryItem } from '@/types/agentTypes'

defineProps<{
  items: RecommendationHistoryItem[]
  loading: boolean
}>()

defineEmits<{
  refresh: []
}>()
</script>
