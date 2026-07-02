<template>
  <div class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/45 p-4">
    <section class="max-h-[90vh] w-full max-w-3xl overflow-hidden rounded-lg bg-white shadow-xl">
      <header class="border-b border-slate-200 px-5 py-4">
        <p class="text-xs font-semibold uppercase tracking-wide text-emerald-700">
          Knowledge Card
        </p>
        <h2 class="mt-1 text-lg font-semibold text-slate-900">
          Case 저장 전 내용 확인
        </h2>
        <p class="mt-1 text-xs text-slate-500">
          저장 후 유사 장애 분석과 RAG 검색 근거로 재사용됩니다.
        </p>
      </header>

      <div class="max-h-[calc(90vh-132px)] space-y-4 overflow-y-auto px-5 py-4">
        <div class="grid gap-3 text-sm md:grid-cols-2">
          <label class="space-y-1">
            <span class="text-xs font-semibold text-slate-500">Fingerprint</span>
            <input
              :value="fingerprint"
              class="w-full rounded border border-slate-200 bg-slate-50 px-3 py-2 text-slate-700"
              readonly
            />
          </label>
          <label class="space-y-1">
            <span class="text-xs font-semibold text-slate-500">Confidence</span>
            <select
              v-model="form.confidence"
              class="w-full rounded border border-slate-300 bg-white px-3 py-2 text-slate-900"
            >
              <option value="HIGH">HIGH</option>
              <option value="MEDIUM">MEDIUM</option>
              <option value="LOW">LOW</option>
            </select>
          </label>
        </div>

        <label class="block space-y-1">
          <span class="text-xs font-semibold text-slate-500">Cause</span>
          <textarea
            v-model="form.cause"
            rows="4"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-900"
          />
        </label>

        <label class="block space-y-1">
          <span class="text-xs font-semibold text-slate-500">Recommendation</span>
          <textarea
            v-model="form.recommendation"
            rows="7"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-900"
          />
        </label>

        <label class="block space-y-1">
          <span class="text-xs font-semibold text-slate-500">Resolution Method</span>
          <textarea
            v-model="form.resolutionMethod"
            rows="4"
            class="w-full rounded border border-slate-300 px-3 py-2 text-sm text-slate-900"
            placeholder="실제 조치 내용과 해결 방법을 입력해주세요."
          />
        </label>
      </div>

      <footer class="flex flex-wrap justify-end gap-2 border-t border-slate-200 px-5 py-4">
        <button
          class="rounded border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700 hover:bg-slate-50"
          @click="emit('cancel')"
        >
          취소
        </button>
        <button
          class="rounded bg-emerald-600 px-3 py-2 text-sm text-white disabled:cursor-not-allowed disabled:bg-slate-300"
          :disabled="!canSave"
          @click="emitSave"
        >
          Knowledge Card 저장
        </button>
      </footer>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, watch } from 'vue'

const props = defineProps<{
  fingerprint: string
  cause: string
  recommendation: string
  resolutionMethod?: string
  confidence: string
}>()

const emit = defineEmits<{
  cancel: []
  save: [
    draft: {
      cause: string
      recommendation: string
      resolutionMethod: string
      confidence: string
    }
  ]
}>()

const form = reactive({
  cause: props.cause,
  recommendation: props.recommendation,
  resolutionMethod: props.resolutionMethod ?? '',
  confidence: props.confidence || 'MEDIUM'
})

watch(
  () => props,
  () => {
    form.cause = props.cause
    form.recommendation = props.recommendation
    form.resolutionMethod = props.resolutionMethod ?? ''
    form.confidence = props.confidence || 'MEDIUM'
  },
  { deep: true }
)

const canSave = computed(
  () => form.recommendation.trim().length > 0 && form.resolutionMethod.trim().length > 0
)

function emitSave() {
  emit('save', {
    cause: form.cause,
    recommendation: form.recommendation,
    resolutionMethod: form.resolutionMethod,
    confidence: form.confidence
  })
}
</script>
