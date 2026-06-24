<template>
  <div class="rounded-xl border bg-white p-4 shadow-sm">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-lg font-semibold">Recommendations</h3>
        <p class="text-xs text-slate-500">
          Case, Recommendation, 예외처리는 각각 사용자 버튼 클릭 후 저장됩니다.
        </p>
      </div>
      <div class="flex flex-wrap gap-2">
        <button
          class="rounded bg-emerald-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          :disabled="!canModerate"
          @click="emit('saveCase')"
        >
          Case 저장
        </button>
        <button
          class="rounded bg-blue-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          :disabled="!canModerate"
          @click="emit('saveRecommendation')"
        >
          Recommend 저장
        </button>
        <button
          class="rounded bg-amber-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          :disabled="!canModerate"
          @click="emit('saveException')"
        >
          예외처리 저장
        </button>
      </div>
    </div>
    <div class="space-y-3">
      <div
        v-if="generatedAnswer"
        class="rounded border border-blue-200 bg-blue-50 p-3 text-sm text-slate-800"
      >
        <p class="mb-1 text-xs font-semibold uppercase text-blue-700">
          Generated Answer
        </p>
        <p class="whitespace-pre-line">{{ generatedAnswer }}</p>
      </div>
      <div
        v-for="item in actions"
        :key="item.action"
        class="rounded border p-3"
      >
        <span class="rounded bg-slate-900 px-2 py-1 text-xs text-white">{{
          item.priority
        }}</span>
        <p class="mt-2 text-sm">{{ item.action }}</p>
        <dl class="mt-2 space-y-1 text-xs text-slate-600">
          <div v-if="item.reason">
            <dt class="inline font-semibold text-slate-700">근거: </dt>
            <dd class="inline">{{ item.reason }}</dd>
          </div>
          <div v-if="item.target">
            <dt class="inline font-semibold text-slate-700">대상: </dt>
            <dd class="inline">{{ item.target }}</dd>
          </div>
          <div v-if="item.expected_effect">
            <dt class="inline font-semibold text-slate-700">기대 효과: </dt>
            <dd class="inline">{{ item.expected_effect }}</dd>
          </div>
          <div v-if="item.risk">
            <dt class="inline font-semibold text-slate-700">주의점: </dt>
            <dd class="inline">{{ item.risk }}</dd>
          </div>
        </dl>
        <p class="text-xs text-slate-500">Owner: {{ item.owner }}</p>
      </div>
      <pre
        class="overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100"
        >{{ verificationText }}</pre
      >
      <button
        class="rounded bg-blue-600 px-3 py-2 text-sm text-white"
        @click="copyText"
      >
        Copy to clipboard
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RecommendedAction } from '@/types/agentTypes'

const props = defineProps<{
  actions: RecommendedAction[]
  verification: string[]
  generatedAnswer?: string | null
  canModerate?: boolean
}>()

const emit = defineEmits<{
  saveCase: []
  saveRecommendation: []
  saveException: []
}>()

const verificationText = computed(() => props.verification.join('\n'))

async function copyText() {
  await navigator.clipboard.writeText(verificationText.value)
}
</script>
