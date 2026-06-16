<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
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
      <div class="flex flex-wrap gap-2">
        <button
          class="rounded border border-slate-300 bg-white px-3 py-2 text-xs text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:bg-slate-100"
          :disabled="loading"
          @click="$emit('refresh')"
        >
          {{ loading ? '조회중...' : 'Recommendation 조회' }}
        </button>
        <button
          class="rounded border border-blue-300 bg-blue-50 px-3 py-2 text-xs text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
          :disabled="loadingKnowledgeCards"
          @click="$emit('fetchKnowledgeCards')"
        >
          {{ loadingKnowledgeCards ? '조회중...' : 'Knowledge Card 조회' }}
        </button>
        <button
          class="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-700 hover:bg-amber-100 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400"
          :disabled="loadingExceptions"
          @click="$emit('fetchExceptions')"
        >
          {{ loadingExceptions ? '조회중...' : '예외처리 조회' }}
        </button>
      </div>
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

    <div class="mt-4 grid gap-4 xl:grid-cols-2">
      <div class="rounded border border-blue-100 bg-blue-50/40 p-3">
        <h3
          class="mb-2 text-xs font-semibold uppercase tracking-wide text-blue-700"
        >
          Registered Knowledge Cards
        </h3>
        <p
          v-if="loadingKnowledgeCards"
          class="py-3 text-center text-xs text-slate-500"
        >
          Knowledge Card 조회중...
        </p>
        <p
          v-else-if="knowledgeCards.length === 0"
          class="py-3 text-center text-xs text-slate-500"
        >
          조회된 Knowledge Card가 없습니다.
        </p>
        <ul v-else class="max-h-60 space-y-2 overflow-y-auto">
          <li
            v-for="card in knowledgeCards"
            :key="card.card_id"
            class="rounded bg-white p-2 text-xs shadow-sm"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="font-mono font-semibold text-blue-700">{{
                card.card_id
              }}</span>
              <span class="rounded bg-blue-100 px-2 py-0.5 text-blue-700">{{
                card.confidence
              }}</span>
            </div>
            <p class="mt-1 font-medium text-slate-800">
              {{ card.fingerprint }}
            </p>
            <p class="mt-1 text-slate-600">{{ card.cause }}</p>
            <p class="mt-1 line-clamp-2 text-slate-500">
              {{ card.recommendation }}
            </p>
          </li>
        </ul>
      </div>

      <div class="rounded border border-amber-100 bg-amber-50/40 p-3">
        <h3
          class="mb-2 text-xs font-semibold uppercase tracking-wide text-amber-700"
        >
          Registered Exceptions
        </h3>
        <p
          v-if="loadingExceptions"
          class="py-3 text-center text-xs text-slate-500"
        >
          예외처리 조회중...
        </p>
        <p
          v-else-if="exceptions.length === 0"
          class="py-3 text-center text-xs text-slate-500"
        >
          조회된 예외처리가 없습니다.
        </p>
        <ul v-else class="max-h-60 space-y-2 overflow-y-auto">
          <li
            v-for="item in exceptions"
            :key="item.fingerprint"
            class="rounded bg-white p-2 text-xs shadow-sm"
          >
            <p class="font-mono font-semibold text-amber-700">
              {{ item.fingerprint }}
            </p>
            <p class="mt-1 text-slate-700">{{ item.reason }}</p>
            <p class="mt-1 text-slate-400">{{ item.created_at }}</p>
          </li>
        </ul>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import type {
  ExceptionRegistryItem,
  KnowledgeCardItem,
  RecommendationHistoryItem
} from '@/types/agentTypes'

defineProps<{
  items: RecommendationHistoryItem[]
  loading: boolean
  knowledgeCards: KnowledgeCardItem[]
  loadingKnowledgeCards: boolean
  exceptions: ExceptionRegistryItem[]
  loadingExceptions: boolean
}>()

defineEmits<{
  refresh: []
  fetchKnowledgeCards: []
  fetchExceptions: []
}>()
</script>
