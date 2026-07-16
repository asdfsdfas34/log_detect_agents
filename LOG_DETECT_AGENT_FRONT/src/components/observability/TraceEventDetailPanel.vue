<template>
  <section class="flex h-full flex-col rounded-lg border border-slate-200 bg-white shadow-sm">
    <div class="flex items-center justify-between border-b border-slate-100 px-4 py-2">
      <p class="text-xs font-semibold uppercase tracking-wide text-slate-500">이벤트 상세</p>
      <button
        v-if="showClose"
        type="button"
        class="text-xs text-slate-500 hover:text-slate-700"
        @click="emit('close')"
      >
        닫기 ✕
      </button>
    </div>

    <div
      v-if="!event"
      class="flex flex-1 items-center justify-center px-4 py-12 text-center text-sm text-slate-400"
    >
      타임라인에서 이벤트를 선택하면 상세 정보가 표시됩니다.
    </div>

    <div v-else class="flex-1 space-y-3 overflow-y-auto px-4 py-3 text-sm" style="max-height: 62vh">
      <div>
        <div class="flex flex-wrap items-center gap-1.5">
          <span
            class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
            :class="kind.chip"
          >
            <span aria-hidden="true">{{ kind.icon }}</span>{{ kind.label }}
          </span>
          <span
            class="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase"
            :class="status.chip"
          >
            <span aria-hidden="true">{{ status.icon }}</span>{{ status.label }}
          </span>
          <span class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">
            {{ event.event_type }}
          </span>
        </div>
        <h3 class="mt-1.5 text-base font-semibold text-slate-900">{{ event.title }}</h3>
        <p class="mt-1 text-slate-600">{{ event.summary }}</p>
      </div>

      <dl class="grid grid-cols-2 gap-x-3 gap-y-1.5 text-xs">
        <div><dt class="text-slate-400">Agent</dt><dd class="text-slate-800">{{ event.agent_name }}</dd></div>
        <div><dt class="text-slate-400">Component</dt><dd class="text-slate-800">{{ event.component }}</dd></div>
        <div><dt class="text-slate-400">Layer</dt><dd class="text-slate-800">{{ layerLabel(event.layer) }}</dd></div>
        <div><dt class="text-slate-400">시각</dt><dd class="text-slate-800">{{ formatClock(event.timestamp) }}</dd></div>
        <div v-if="event.duration_ms != null">
          <dt class="text-slate-400">Duration</dt>
          <dd class="text-slate-800">{{ formatDuration(event.duration_ms) }}</dd>
        </div>
        <div v-if="event.attempt != null">
          <dt class="text-slate-400">시도</dt>
          <dd class="text-slate-800">{{ event.attempt }} / {{ event.max_attempts ?? '—' }}</dd>
        </div>
      </dl>

      <div
        v-if="event.decision_summary"
        class="rounded border border-violet-100 bg-violet-50 px-3 py-2 text-xs text-violet-800"
      >
        <p class="font-semibold">선택 · 결정 근거</p>
        <p class="mt-0.5 whitespace-pre-line">{{ event.decision_summary }}</p>
      </div>

      <div v-if="nextAgent" class="rounded border border-indigo-100 bg-indigo-50 px-3 py-2 text-xs">
        <p class="font-semibold text-indigo-800">다음 Agent</p>
        <p class="mt-0.5 text-indigo-700">{{ nextAgent }}</p>
      </div>

      <div v-if="selectedSkills.length" class="rounded border border-cyan-100 bg-cyan-50 px-3 py-2 text-xs">
        <p class="font-semibold text-cyan-800">선택된 스킬</p>
        <p class="mt-0.5 text-cyan-700">{{ selectedSkills.join(', ') }}</p>
      </div>

      <div v-if="toolName" class="rounded border border-teal-100 bg-teal-50 px-3 py-2 text-xs">
        <p class="font-semibold text-teal-800">Tool</p>
        <p class="mt-0.5 text-teal-700">{{ toolName }}</p>
        <p v-if="event.input_summary?.field_names?.length" class="mt-1 text-teal-700">
          입력 필드: {{ event.input_summary.field_names.join(', ') }}
        </p>
        <p v-if="event.output_summary" class="mt-1 text-teal-700">
          결과: {{ outputSummaryLabel }}
        </p>
      </div>

      <div v-if="validatorInfo" class="rounded border px-3 py-2 text-xs" :class="validatorInfo.box">
        <p class="font-semibold">Validator</p>
        <p class="mt-0.5">{{ validatorInfo.text }}</p>
      </div>

      <div v-if="qualityInfo" class="rounded border border-rose-100 bg-rose-50 px-3 py-2 text-xs text-rose-800">
        <p class="font-semibold">품질 평가</p>
        <p class="mt-0.5">{{ qualityInfo }}</p>
      </div>

      <div v-if="event.evidence_refs.length" class="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs">
        <p class="font-semibold text-slate-700">Evidence 참조</p>
        <p class="mt-0.5 break-words text-slate-600">{{ event.evidence_refs.join(', ') }}</p>
      </div>

      <div v-if="event.error" class="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
        <p class="font-semibold">오류</p>
        <p class="mt-0.5">유형: {{ event.error.type }}</p>
        <p class="mt-0.5">{{ event.error.summary }}</p>
      </div>

      <div v-if="event.fallback_used" class="rounded border border-orange-200 bg-orange-50 px-3 py-2 text-xs text-orange-700">
        graceful degradation: fallback 경로가 사용되었습니다.
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { AgentTraceEvent } from '@/types/agentTypes'
import {
  formatClock,
  formatDuration,
  kindMeta,
  layerLabel,
  statusMeta
} from '@/components/observability/observability'

const props = defineProps<{
  event: AgentTraceEvent | null
  showClose: boolean
}>()

const emit = defineEmits<{ (event: 'close'): void }>()

const kind = computed(() => kindMeta(props.event?.kind ?? 'request'))
const status = computed(() => statusMeta(props.event?.status ?? 'planned'))

function metaString(key: string): string | null {
  const value = props.event?.metadata?.[key]
  return typeof value === 'string' && value ? value : null
}

function metaNumber(key: string): number | null {
  const value = props.event?.metadata?.[key]
  return typeof value === 'number' ? value : null
}

const nextAgent = computed(() => metaString('next_agent'))
const toolName = computed(() => metaString('tool_name'))

const selectedSkills = computed<string[]>(() => {
  const value = props.event?.metadata?.selected_skill_ids
  if (Array.isArray(value)) return value.map((item) => String(item))
  return []
})

const outputSummaryLabel = computed(() => {
  const output = props.event?.output_summary
  if (!output) return ''
  if (output.type === 'list') return `list ${output.count ?? 0}건`
  if (output.type === 'object') return `object ${output.field_count ?? 0}개 필드`
  if (output.type === 'text') return `text ${output.length ?? 0}자`
  return output.type ?? ''
})

const validatorInfo = computed(() => {
  if (props.event?.kind !== 'validation') return null
  const passed = props.event.metadata?.passed === true
  const validatorType = metaString('validator_type') ?? '검증'
  return passed
    ? { box: 'border-lime-200 bg-lime-50 text-lime-800', text: `${validatorType} 통과` }
    : {
        box: 'border-red-200 bg-red-50 text-red-700',
        text: `${validatorType} 실패 — ${props.event.summary}`
      }
})

const qualityInfo = computed(() => {
  const score = metaNumber('score')
  const threshold = metaNumber('threshold')
  if (score == null) return null
  const attempt = metaNumber('attempt')
  const base = `점수 ${score}/100${threshold != null ? ` · 통과 기준 ${threshold}` : ''}`
  return attempt != null ? `${base} · 시도 ${attempt}` : base
})
</script>
