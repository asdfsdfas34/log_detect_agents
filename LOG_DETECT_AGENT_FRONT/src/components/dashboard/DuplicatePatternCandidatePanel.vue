<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
      <div>
        <h3 class="text-lg font-semibold text-slate-900">
          Duplicate Pattern Candidates
        </h3>
        <p class="text-xs text-slate-500">
          {{ candidates.length }} pending candidates
        </p>
      </div>
      <button
        class="rounded border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        type="button"
        :disabled="loading"
        @click="emit('refresh')"
      >
        Refresh
      </button>
    </div>

    <div
      v-if="loading"
      class="rounded border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500"
    >
      Loading candidates...
    </div>

    <div
      v-else-if="candidates.length === 0"
      class="rounded border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500"
    >
      No duplicate pattern candidates.
    </div>

    <div v-else class="space-y-3">
      <article
        v-for="candidate in candidates"
        :key="candidate.candidate_key"
        class="rounded border border-slate-200 p-3"
      >
        <div class="mb-3 flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <span class="font-mono text-xs font-semibold text-slate-700">
                {{ candidate.candidate_key }}
              </span>
              <span
                class="rounded bg-cyan-100 px-2 py-1 text-xs font-semibold text-cyan-700"
              >
                {{ confidencePercent(candidate.confidence) }}%
              </span>
              <span
                class="rounded bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-600"
              >
                {{ candidate.service_name }}
              </span>
              <span
                class="rounded px-2 py-1 text-xs font-semibold"
                :class="levelClass(candidate.log_level)"
              >
                {{ candidate.log_level }}
              </span>
            </div>
            <p class="mt-2 text-sm text-slate-600">
              {{ candidate.reason }}
            </p>
          </div>
          <div class="flex shrink-0 gap-2">
            <button
              class="rounded border border-emerald-200 px-3 py-1.5 text-xs font-semibold text-emerald-700 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              :disabled="busyKey === candidate.candidate_key"
              @click="emit('approve', candidate)"
            >
              Approve
            </button>
            <button
              class="rounded border border-rose-200 px-3 py-1.5 text-xs font-semibold text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50"
              type="button"
              :disabled="busyKey === candidate.candidate_key"
              @click="emit('reject', candidate)"
            >
              Reject
            </button>
          </div>
        </div>

        <dl class="grid gap-3 text-xs md:grid-cols-3">
          <div>
            <dt class="mb-1 font-semibold text-slate-500">Fingerprints</dt>
            <dd class="flex flex-wrap gap-1">
              <button
                v-for="fingerprint in candidate.fingerprints"
                :key="fingerprint"
                class="rounded bg-slate-100 px-2 py-1 font-mono text-slate-700 hover:bg-blue-50 hover:text-blue-700 hover:underline"
                type="button"
                @click="selectedFingerprint = detailFor(candidate, fingerprint)"
              >
                {{ fingerprint }}
              </button>
            </dd>
          </div>
          <div class="md:col-span-2">
            <dt class="mb-1 font-semibold text-slate-500">Template</dt>
            <dd
              class="break-all rounded bg-slate-50 px-2 py-1 font-mono text-slate-700"
            >
              {{ candidate.suggested_template }}
            </dd>
          </div>
        </dl>

        <details class="mt-3">
          <summary class="cursor-pointer text-xs font-semibold text-slate-500">
            Regex
          </summary>
          <pre
            class="mt-2 max-h-32 overflow-y-auto whitespace-pre-wrap rounded bg-slate-950 p-3 text-xs text-slate-100"
            >{{ candidate.suggested_regex }}</pre
          >
        </details>
      </article>
    </div>

    <div
      v-if="selectedFingerprint"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="selectedFingerprint = null"
    >
      <div
        class="max-h-[85vh] w-full max-w-4xl overflow-hidden rounded-lg bg-white shadow-xl"
      >
        <div class="flex items-center justify-between border-b px-4 py-3">
          <div>
            <h4 class="font-mono text-base font-semibold text-slate-900">
              {{ selectedFingerprint.fingerprint }}
            </h4>
            <p class="text-xs text-slate-500">
              {{ selectedFingerprint.service_name || '-' }} /
              {{ selectedFingerprint.log_level || '-' }}
            </p>
          </div>
          <button
            class="rounded px-2 py-1 text-sm text-slate-500 hover:bg-slate-100"
            type="button"
            @click="selectedFingerprint = null"
          >
            Close
          </button>
        </div>

        <div class="max-h-[calc(85vh-64px)] space-y-4 overflow-y-auto p-4">
          <dl class="grid gap-3 text-xs text-slate-600 md:grid-cols-3">
            <div>
              <dt class="font-semibold text-slate-500">Count</dt>
              <dd>{{ selectedFingerprint.occurrence_count ?? '-' }}</dd>
            </div>
            <div>
              <dt class="font-semibold text-slate-500">First Seen</dt>
              <dd>{{ selectedFingerprint.first_seen || '-' }}</dd>
            </div>
            <div>
              <dt class="font-semibold text-slate-500">Last Seen</dt>
              <dd>{{ selectedFingerprint.last_seen || '-' }}</dd>
            </div>
          </dl>

          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Error Message
            </h5>
            <pre
              class="whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800"
              >{{ selectedFingerprint.message || '-' }}</pre
            >
          </section>

          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Normalized Message
            </h5>
            <pre
              class="whitespace-pre-wrap rounded border border-slate-200 bg-slate-50 p-3 text-sm text-slate-800"
              >{{ selectedFingerprint.normalized_message || '-' }}</pre
            >
          </section>

          <section>
            <h5 class="mb-2 text-sm font-semibold text-slate-700">
              Stack Trace
            </h5>
            <pre
              class="max-h-72 overflow-y-auto whitespace-pre-wrap rounded border border-slate-200 bg-slate-950 p-3 text-xs text-slate-100"
              >{{ selectedFingerprint.stacktrace || '-' }}</pre
            >
          </section>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import type { DuplicatePatternCandidate } from '@/types/agentTypes'

type FingerprintDetail = NonNullable<
  DuplicatePatternCandidate['fingerprint_details']
>[string]

defineProps<{
  candidates: DuplicatePatternCandidate[]
  loading: boolean
  busyKey?: string | null
}>()

const emit = defineEmits<{
  refresh: []
  approve: [candidate: DuplicatePatternCandidate]
  reject: [candidate: DuplicatePatternCandidate]
}>()

const selectedFingerprint = ref<FingerprintDetail | null>(null)

function confidencePercent(confidence: number): number {
  return Math.round((confidence || 0) * 100)
}

function levelClass(level?: string): string {
  if (level === 'ERROR') return 'bg-red-100 text-red-700'
  if (level === 'WARN') return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-600'
}

function detailFor(
  candidate: DuplicatePatternCandidate,
  fingerprint: string
): FingerprintDetail {
  return (
    candidate.fingerprint_details?.[fingerprint] ?? {
      fingerprint
    }
  )
}
</script>
