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
            <th class="px-3 py-2 text-right">Action</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100 bg-white">
          <tr
            v-for="item in pagedItems"
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
            <td class="whitespace-nowrap px-3 py-2 text-right">
              <button
                class="rounded-full border border-red-200 px-2 py-0.5 text-xs font-semibold text-red-600 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="loading"
                aria-label="Delete saved recommendation"
                @click="$emit('deleteRecommendation', item.id)"
              >
                ×
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <div
        class="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600"
      >
        <span>
          Page {{ currentPage }} / {{ pageCount }} -
          {{ items.length }} recommendations
        </span>
        <div class="flex items-center gap-2">
          <button
            class="rounded border border-slate-300 bg-white px-3 py-1 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="currentPage === 1"
            @click="previousPage"
          >
            Previous
          </button>
          <button
            class="rounded border border-slate-300 bg-white px-3 py-1 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="currentPage === pageCount"
            @click="nextPage"
          >
            Next
          </button>
        </div>
      </div>
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
            class="cursor-pointer rounded bg-white p-2 text-xs shadow-sm hover:bg-blue-50"
            role="button"
            tabindex="0"
            @click="openKnowledgeCard(card)"
            @keydown.enter="openKnowledgeCard(card)"
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
            class="cursor-pointer rounded bg-white p-2 text-xs shadow-sm hover:bg-amber-50"
            role="button"
            tabindex="0"
            @click="openException(item)"
            @keydown.enter="openException(item)"
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

    <div
      v-if="detail"
      class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
      @click.self="closeDetail"
    >
      <div class="w-full max-w-2xl rounded-lg bg-white shadow-xl">
        <div class="flex items-start justify-between gap-4 border-b border-slate-200 p-4">
          <div>
            <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">
              {{ detail.kind }}
            </p>
            <h3 class="mt-1 break-all font-mono text-sm font-semibold text-slate-900">
              {{ detail.fingerprint }}
            </h3>
          </div>
          <button
            class="rounded border border-slate-300 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
            @click="closeDetail"
          >
            Close
          </button>
        </div>
        <div class="grid gap-3 p-4 text-sm text-slate-700 sm:grid-cols-2">
          <div>
            <p class="text-xs font-semibold uppercase text-slate-400">Level</p>
            <p class="mt-1 font-semibold">{{ detail.log_level || '-' }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold uppercase text-slate-400">Service</p>
            <p class="mt-1">{{ detail.service_name || '-' }}</p>
          </div>
          <div class="sm:col-span-2">
            <p class="text-xs font-semibold uppercase text-slate-400">Error Message</p>
            <p class="mt-1 whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3">
              {{ detail.message || '-' }}
            </p>
          </div>
          <div class="sm:col-span-2">
            <p class="text-xs font-semibold uppercase text-slate-400">
              {{ detail.kind === 'Knowledge Card' ? 'Cause' : 'Reason' }}
            </p>
            <p class="mt-1 whitespace-pre-wrap">{{ detail.primaryText || '-' }}</p>
          </div>
          <div v-if="detail.secondaryText" class="sm:col-span-2">
            <p class="text-xs font-semibold uppercase text-slate-400">Recommendation</p>
            <p class="mt-1 whitespace-pre-wrap">{{ detail.secondaryText }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold uppercase text-slate-400">Created</p>
            <p class="mt-1">{{ detail.created_at || '-' }}</p>
          </div>
          <div>
            <p class="text-xs font-semibold uppercase text-slate-400">Confidence</p>
            <p class="mt-1">{{ detail.confidence || '-' }}</p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import type {
  ExceptionRegistryItem,
  KnowledgeCardItem,
  RecommendationHistoryItem
} from '@/types/agentTypes'

const props = defineProps<{
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
  deleteRecommendation: [recommendationId: number]
}>()

interface DetailView {
  kind: 'Knowledge Card' | 'Exception'
  fingerprint: string
  message?: string
  log_level?: string
  service_name?: string
  primaryText?: string
  secondaryText?: string
  confidence?: string
  created_at?: string
}

const detail = ref<DetailView | null>(null)
const pageSize = 5
const currentPage = ref(1)

const pageCount = computed(() =>
  Math.max(1, Math.ceil(props.items.length / pageSize))
)
const pagedItems = computed(() => {
  const start = (currentPage.value - 1) * pageSize
  return props.items.slice(start, start + pageSize)
})

watch(
  () => props.items.length,
  () => {
    if (currentPage.value > pageCount.value) {
      currentPage.value = pageCount.value
    }
    if (currentPage.value < 1) {
      currentPage.value = 1
    }
  }
)

function previousPage() {
  currentPage.value = Math.max(1, currentPage.value - 1)
}

function nextPage() {
  currentPage.value = Math.min(pageCount.value, currentPage.value + 1)
}

function openKnowledgeCard(card: KnowledgeCardItem) {
  detail.value = {
    kind: 'Knowledge Card',
    fingerprint: card.fingerprint,
    message: card.message,
    log_level: card.log_level,
    service_name: card.service_name,
    primaryText: card.cause,
    secondaryText: card.recommendation,
    confidence: card.confidence,
    created_at: card.created_at
  }
}

function openException(item: ExceptionRegistryItem) {
  detail.value = {
    kind: 'Exception',
    fingerprint: item.fingerprint,
    message: item.message,
    log_level: item.log_level,
    service_name: item.service_name,
    primaryText: item.reason,
    created_at: item.created_at
  }
}

function closeDetail() {
  detail.value = null
}
</script>
