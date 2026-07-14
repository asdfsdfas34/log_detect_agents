<template>
  <section class="space-y-4">
    <!-- Preview status banner: this screen is a concept preview, not a prediction -->
    <div
      class="rounded-lg border border-amber-300 bg-amber-50 p-4 text-amber-900"
    >
      <div class="flex flex-wrap items-center gap-2">
        <span
          class="rounded bg-amber-500 px-2 py-0.5 text-xs font-semibold uppercase tracking-wide text-white"
        >
          Concept Preview
        </span>
        <span class="text-sm font-semibold">
          RecFM applicability & data-readiness preview — not a prediction result.
        </span>
      </div>
      <ul class="mt-2 grid gap-1 text-xs sm:grid-cols-2 lg:grid-cols-3">
        <li>• No trained RecFM model</li>
        <li>• No production inference</li>
        <li>• Existing trajectory data only</li>
        <li>• 10-minute time windows</li>
        <li>• Visualization Only</li>
        <li>• Model Not Trained</li>
      </ul>
    </div>

    <!-- Data class legend -->
    <div class="flex flex-wrap items-center gap-3 text-xs text-slate-600">
      <span class="font-semibold uppercase tracking-wide text-slate-500">Data class:</span>
      <span class="inline-flex items-center gap-1">
        <span class="h-3 w-3 rounded-full bg-blue-500"></span> Observed
      </span>
      <span class="inline-flex items-center gap-1">
        <span class="h-3 w-3 rounded-full bg-emerald-500"></span> Derived
      </span>
      <span class="inline-flex items-center gap-1">
        <span class="h-3 w-3 rounded-full bg-purple-400"></span> Simulation
      </span>
      <span class="inline-flex items-center gap-1">
        <span class="h-3 w-3 rounded-full bg-slate-300"></span> Model Output (none)
      </span>
    </div>

    <!-- No 10min data -->
    <div
      v-if="!hasTenMinuteData"
      class="rounded-lg border border-slate-300 bg-slate-50 p-6 text-sm text-slate-700"
    >
      <p class="text-base font-semibold text-slate-900">
        RecFM Readiness: <span class="text-rose-600">Insufficient</span>
      </p>
      <dl class="mt-3 grid gap-2 sm:grid-cols-2">
        <div>
          <dt class="text-xs uppercase text-slate-500">Required Bucket</dt>
          <dd class="font-mono">10min</dd>
        </div>
        <div>
          <dt class="text-xs uppercase text-slate-500">Available Buckets</dt>
          <dd class="font-mono">{{ availableBuckets.join(', ') || '(none)' }}</dd>
        </div>
      </dl>
      <p class="mt-3 rounded bg-white p-3 text-slate-600">
        10-minute trajectory data is not available. Run
        <code class="rounded bg-slate-100 px-1">backfill_10min_metrics.py</code>
        to aggregate existing logs into 10-minute windows, then re-run analysis.
        30-minute data is never substituted for 10-minute data.
      </p>
    </div>

    <template v-else>
      <!-- Readiness -->
      <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
            RecFM Data Readiness
            <span class="ml-1 text-[10px] font-normal normal-case text-emerald-600">
              (Derived)
            </span>
          </h3>
          <span
            class="rounded px-2 py-0.5 text-xs font-semibold uppercase"
            :class="readinessBadgeClass"
          >
            {{ readiness.level }}
          </span>
        </div>

        <div class="mt-3 grid gap-3 text-sm md:grid-cols-3 xl:grid-cols-4">
          <ReadinessStat label="10min Event Windows" :value="readiness.eventWindowCount" />
          <ReadinessStat label="10min State Vectors" :value="readiness.stateVectorCount" />
          <ReadinessStat label="10min Trajectories" :value="readiness.trajectoryCount" />
          <ReadinessStat label="10min Clusters" :value="readiness.trajectoryClusterCount" />
          <ReadinessStat label="Feature Schema" :value="readiness.featureSchemaVersion" />
          <ReadinessStat label="Vector Dimension" :value="readiness.stateVectorDimension" />
          <ReadinessStat
            label="Window Length"
            :value="`${readiness.trajectoryWindowLength} windows`"
          />
          <ReadinessStat
            label="Observed Duration"
            :value="`${readiness.observedDurationMinutes} min`"
          />
          <ReadinessStat
            label="Composable Trajectories"
            :value="readiness.composableTrajectoryCount"
          />
          <ReadinessStat
            label="Target Candidates"
            :value="readiness.targetCandidateCount"
          />
          <ReadinessStat
            label="Missing 10min Windows"
            :value="readiness.missingWindowCount"
          />
          <ReadinessStat
            label="Vectors w/ incident_id"
            :value="`${(readiness.vectorsWithIncidentIdRatio * 100).toFixed(0)}%`"
          />
        </div>

        <div class="mt-3 flex flex-wrap gap-2 text-xs">
          <span
            v-for="(count, label) in readiness.labelDistribution"
            :key="label"
            class="rounded bg-slate-100 px-2 py-0.5 text-slate-600"
          >
            {{ label }}: {{ count }}
          </span>
          <span
            v-if="readiness.availableServices.length"
            class="rounded bg-slate-100 px-2 py-0.5 text-slate-600"
          >
            services: {{ readiness.availableServices.join(', ') }}
          </span>
        </div>

        <ul v-if="readiness.messages.length" class="mt-3 space-y-1 text-xs text-slate-600">
          <li v-for="msg in readiness.messages" :key="msg">• {{ msg }}</li>
        </ul>

        <p class="mt-3 rounded bg-slate-50 p-2 text-xs italic text-slate-500">
          Readiness indicates dataset preparation only, not model accuracy or
          production readiness.
        </p>
      </div>

      <!-- Trajectory selection + RecFM input structure -->
      <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div class="flex flex-wrap items-center justify-between gap-2">
          <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
            RecFM Input Structure
            <span class="ml-1 text-[10px] font-normal normal-case text-blue-600">
              (Observed input)
            </span>
          </h3>
          <label class="flex items-center gap-2 text-xs text-slate-600">
            <span>Trajectory</span>
            <select
              class="max-w-xs rounded border border-slate-300 bg-white px-2 py-1 text-xs"
              :value="selectedTrajectoryId ?? ''"
              @change="onSelectTrajectory(($event.target as HTMLSelectElement).value)"
            >
              <option
                v-for="t in trajectories10min"
                :key="t.trajectory_id"
                :value="t.trajectory_id"
              >
                {{ trajectoryOptionLabel(t) }}
              </option>
            </select>
          </label>
        </div>

        <div v-if="!selectedTrajectory" class="mt-3 text-sm text-slate-500">
          No 10-minute trajectory selected.
        </div>

        <template v-else>
          <!-- Input / target structure summary -->
          <div class="mt-3 grid gap-2 text-sm sm:grid-cols-3">
            <div class="rounded border border-blue-200 bg-blue-50 p-3">
              <p class="text-xs uppercase text-blue-700">Initial State</p>
              <p class="font-mono text-blue-900">x₀ @ {{ observedSteps[0]?.timeLabel ?? '-' }}</p>
            </div>
            <div class="rounded border border-blue-200 bg-blue-50 p-3">
              <p class="text-xs uppercase text-blue-700">Observed States (input)</p>
              <p class="font-mono text-blue-900">x₁ … x{{ subscript(observedSteps.length - 1) }}</p>
            </div>
            <div class="rounded border border-slate-200 bg-slate-50 p-3">
              <p class="text-xs uppercase text-slate-600">Target State Candidate</p>
              <p class="font-mono text-slate-800">
                x{{ subscript(observedSteps.length) }}
                <span class="text-xs">
                  ({{ historicalTargets.length ? '미래 시점 관측 target 후보' : '없음' }})
                </span>
              </p>
            </div>
          </div>

          <!-- Conditioning context -->
          <div class="mt-3 overflow-hidden rounded border border-slate-200">
            <div class="grid grid-cols-2 gap-px bg-slate-200 text-xs md:grid-cols-4">
              <ContextCell label="service" :value="selectedTrajectory.service_name" />
              <ContextCell label="bucket size" value="10min" />
              <ContextCell label="start time" :value="observedSteps[0]?.timeLabel ?? '-'" />
              <ContextCell label="end time" :value="lastObservedStep?.timeLabel ?? '-'" />
              <ContextCell label="window length" :value="`${observedSteps.length}`" />
              <ContextCell
                label="observed duration"
                :value="`${observedSteps.length * 10} min`"
              />
              <ContextCell label="max risk" :value="`${selectedTrajectory.max_risk_score}`" />
              <ContextCell label="anomaly count" :value="`${selectedTrajectory.anomaly_count}`" />
              <ContextCell label="total events" :value="`${selectedTrajectory.total_events}`" />
              <ContextCell label="state dimension" :value="`${readiness.stateVectorDimension}`" />
              <ContextCell
                label="feature schema"
                :value="readiness.featureSchemaVersion"
              />
              <ContextCell label="top fingerprint" :value="topFingerprintLabel" />
            </div>
          </div>

          <!-- Observed trajectory steps -->
          <div class="mt-4">
            <p class="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              Observed Trajectory ({{ observedSteps.length }} windows /
              {{ observedSteps.length * 10 }} minutes)
              <span class="text-[10px] font-normal normal-case text-blue-600">— Observed, solid path</span>
            </p>
            <div class="overflow-x-auto">
              <table class="min-w-full text-left text-xs">
                <thead class="text-slate-500">
                  <tr class="border-b border-slate-200">
                    <th class="px-2 py-1">Step</th>
                    <th class="px-2 py-1">Time</th>
                    <th class="px-2 py-1">Label</th>
                    <th class="px-2 py-1">Events</th>
                    <th class="px-2 py-1">Err%</th>
                    <th class="px-2 py-1">Warn%</th>
                    <th class="px-2 py-1">Anom</th>
                    <th class="px-2 py-1">Max risk</th>
                    <th class="px-2 py-1">Top FP</th>
                  </tr>
                </thead>
                <tbody>
                  <tr
                    v-for="step in observedSteps"
                    :key="step.index"
                    class="border-b border-slate-100"
                  >
                    <td class="px-2 py-1 font-mono">{{ step.symbol }}</td>
                    <td class="px-2 py-1 font-mono">{{ step.timeLabel }}</td>
                    <td class="px-2 py-1">
                      <span class="rounded px-1.5 py-0.5" :class="labelClass(step.label)">
                        {{ step.label }}
                      </span>
                    </td>
                    <td class="px-2 py-1">{{ step.totalEvents }}</td>
                    <td class="px-2 py-1">{{ (step.errorRatio * 100).toFixed(0) }}</td>
                    <td class="px-2 py-1">{{ (step.warnRatio * 100).toFixed(0) }}</td>
                    <td class="px-2 py-1">{{ step.anomalyCount }}</td>
                    <td class="px-2 py-1">{{ step.maxRisk }}</td>
                    <td class="px-2 py-1 truncate font-mono">{{ step.topFingerprint }}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </template>
      </div>

      <!-- Recursive Horizon Preview -->
      <div
        v-if="selectedTrajectory"
        class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
      >
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Recursive Horizon 미리보기
        </h3>
        <div class="mt-3 grid gap-3 md:grid-cols-3">
          <div
            v-for="horizon in horizons"
            :key="horizon.windows"
            class="rounded border p-3 text-sm"
            :class="
              horizon.windows === store.selectedRecFMHorizon
                ? 'border-blue-400 bg-blue-50'
                : 'border-slate-200'
            "
            role="button"
            tabindex="0"
            @click="selectHorizon(horizon.windows)"
            @keydown.enter.prevent="selectHorizon(horizon.windows)"
            @keydown.space.prevent="selectHorizon(horizon.windows)"
          >
            <p class="font-semibold text-slate-800">
              {{ horizon.windows }}-window horizon
            </p>
            <p class="text-xs text-slate-500">예측 horizon: {{ horizon.horizonMinutes }}분</p>
            <dl class="mt-2 space-y-1 text-xs text-slate-600">
              <div class="flex justify-between">
                <dt>필요한 input window</dt>
                <dd>{{ horizon.requiredInputWindows }}</dd>
              </div>
              <div class="flex justify-between">
                <dt>target 후보</dt>
                <dd class="font-mono">
                  {{ horizon.targetSymbols.join(', ') || '—' }}
                </dd>
              </div>
              <div class="flex justify-between">
                <dt>미래 시점 관측 target</dt>
                <dd>{{ horizon.historicalTargetsAvailable ? '있음' : '없음' }}</dd>
              </div>
              <div class="flex justify-between">
                <dt>학습 sample</dt>
                <dd>{{ horizon.trainingSampleComposable ? '구성 가능' : '구성 불가능' }}</dd>
              </div>
            </dl>
            <p class="mt-2 rounded bg-slate-100 px-2 py-0.5 text-[11px] text-slate-600">
              상태: {{ horizon.status }}
            </p>
            <p v-if="horizon.missingRequirement" class="mt-1 text-[11px] text-rose-600">
              {{ horizon.missingRequirement }}
            </p>
          </div>
        </div>
      </div>

      <!-- Recursive Scale Concept -->
      <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Recursive Scale 개념
        </h3>
        <div class="mt-3 overflow-x-auto">
          <table class="min-w-full text-left text-xs">
            <thead class="text-slate-500">
              <tr class="border-b border-slate-200">
                <th class="px-2 py-1">Scale</th>
                <th class="px-2 py-1">필요한 target 수</th>
                <th class="px-2 py-1">미래 target sample</th>
                <th class="px-2 py-1">누락 sample</th>
                <th class="px-2 py-1">구현 상태</th>
              </tr>
            </thead>
            <tbody>
              <tr class="border-b border-slate-100">
                <td class="px-2 py-1">Fine Scale: 10분 상태</td>
                <td class="px-2 py-1">1 (step당)</td>
                <td class="px-2 py-1">{{ readiness.targetCandidateCount }}</td>
                <td class="px-2 py-1">{{ readiness.missingWindowCount }}</td>
                <td class="px-2 py-1">데이터 구성: 미리보기</td>
              </tr>
              <tr class="border-b border-slate-100">
                <td class="px-2 py-1">1-step: 10분</td>
                <td class="px-2 py-1">1</td>
                <td class="px-2 py-1">{{ horizonSampleCount(1) }}</td>
                <td class="px-2 py-1">{{ horizonMissingCount(1) }}</td>
                <td class="px-2 py-1">학습: 미구현</td>
              </tr>
              <tr class="border-b border-slate-100">
                <td class="px-2 py-1">2-step: 20분</td>
                <td class="px-2 py-1">2</td>
                <td class="px-2 py-1">{{ horizonSampleCount(2) }}</td>
                <td class="px-2 py-1">{{ horizonMissingCount(2) }}</td>
                <td class="px-2 py-1">추론: 미구현</td>
              </tr>
              <tr>
                <td class="px-2 py-1">4-step: 40분</td>
                <td class="px-2 py-1">4</td>
                <td class="px-2 py-1">{{ horizonSampleCount(4) }}</td>
                <td class="px-2 py-1">{{ horizonMissingCount(4) }}</td>
                <td class="px-2 py-1">운영 사용: 비활성화</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Conceptual Flow Path -->
      <div
        v-if="selectedTrajectory && flowPoints.length >= 2"
        class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
      >
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
          개념적 Flow Path
        </h3>
        <div class="mt-2 flex flex-wrap gap-3 text-xs">
          <label class="flex items-center gap-1">
            <span>측정 지표</span>
            <select
              v-model="flowMetric"
              class="rounded border border-slate-300 bg-white px-2 py-1"
            >
              <option value="totalEvents">전체 이벤트</option>
              <option value="errorRatio">오류 비율</option>
              <option value="anomalyCount">anomaly 수</option>
              <option value="maxRisk">위험도</option>
            </select>
          </label>
          <span class="inline-flex items-center gap-1 text-slate-600">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#3b82f6" stroke-width="2" /></svg>
            관측값(실선)
          </span>
          <span class="inline-flex items-center gap-1 text-slate-600">
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#a855f7" stroke-width="2" stroke-dasharray="4 3" /></svg>
            선형 보간(시각화 전용)
          </span>
        </div>

        <svg :viewBox="`0 0 ${flowW} ${flowH}`" class="mt-2 w-full" role="img"
             aria-label="관측된 10분 trajectory의 개념적 flow path">
          <!-- axes -->
          <line :x1="pad" :y1="flowH - pad" :x2="flowW - pad" :y2="flowH - pad" stroke="#cbd5e1" stroke-width="1" />
          <line :x1="pad" :y1="pad" :x2="pad" :y2="flowH - pad" stroke="#cbd5e1" stroke-width="1" />
          <!-- dashed simulation (linear interpolation between first and last observed) -->
          <line
            :x1="flowX(0)"
            :y1="flowY(flowValues[0])"
            :x2="flowX(1)"
            :y2="flowY(flowValues[flowValues.length - 1])"
            stroke="#a855f7"
            stroke-width="1.5"
            stroke-dasharray="4 3"
          />
          <!-- observed solid path -->
          <polyline
            :points="observedPolyline"
            fill="none"
            stroke="#3b82f6"
            stroke-width="2"
          />
          <!-- observed points -->
          <g v-for="(pt, idx) in flowPoints" :key="idx">
            <circle :cx="flowX(pt.t)" :cy="flowY(flowValues[idx])" r="4" fill="#3b82f6" />
            <text :x="flowX(pt.t)" :y="flowH - pad + 14" text-anchor="middle"
                  class="fill-slate-500" font-size="9">
              x{{ subscript(idx) }}
            </text>
          </g>
          <!-- normalized time axis labels -->
          <text :x="pad" :y="flowH - 4" class="fill-slate-400" font-size="9">t = 0</text>
          <text :x="flowW - pad" :y="flowH - 4" text-anchor="end" class="fill-slate-400" font-size="9">t = 1</text>
        </svg>

        <p class="mt-1 text-[11px] italic text-purple-600">
          점선은 시각화 전용 선형 보간입니다. RecFM 추론 결과가 아니며,
          저장하거나 추천 근거로 사용하지 않습니다.
        </p>
      </div>

      <!-- Roadmap -->
      <div class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <h3 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
          RecFM Roadmap
        </h3>
        <div class="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <div
            v-for="phase in roadmap"
            :key="phase.title"
            class="rounded border p-3 text-xs"
            :class="phase.current ? 'border-blue-400 bg-blue-50' : 'border-slate-200'"
          >
            <p class="font-semibold text-slate-800">
              {{ phase.title }}
              <span v-if="phase.current" class="ml-1 rounded bg-blue-500 px-1.5 py-0.5 text-[10px] text-white">
                현재
              </span>
            </p>
            <ul class="mt-2 space-y-1 text-slate-600">
              <li v-for="item in phase.items" :key="item">• {{ item }}</li>
            </ul>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>

<script setup lang="ts">
import { computed, h, ref } from 'vue'
import { useLogDetectStore } from '@/stores/logDetectStore'
import type {
  EventTimeWindow,
  RecFMFlowPoint,
  RecFMHorizonPreview,
  RecFMReadiness,
  RecFMStateStep,
  SystemStateVector,
  Trajectory,
  TrajectoryCluster
} from '@/types/agentTypes'

const props = defineProps<{
  eventWindows10min: EventTimeWindow[]
  stateVectors10min: SystemStateVector[]
  trajectories10min: Trajectory[]
  trajectoryClusters10min: TrajectoryCluster[]
  availableBuckets: string[]
  windowLength: number
}>()

const store = useLogDetectStore()

const BUCKET_STEP_MINUTES = 10

// Small functional components for repeated cells (kept local, no new files).
const ReadinessStat = (p: { label: string; value: string | number }) =>
  h('div', { class: 'rounded border border-slate-200 p-2' }, [
    h('p', { class: 'text-[10px] uppercase text-slate-500' }, p.label),
    h('p', { class: 'mt-0.5 text-lg font-semibold text-slate-900' }, String(p.value))
  ])
ReadinessStat.props = ['label', 'value']

const ContextCell = (p: { label: string; value: string }) =>
  h('div', { class: 'bg-white p-2' }, [
    h('p', { class: 'text-[10px] uppercase text-slate-500' }, p.label),
    h('p', { class: 'font-mono text-slate-800' }, p.value || '-')
  ])
ContextCell.props = ['label', 'value']

const hasTenMinuteData = computed(
  () =>
    props.stateVectors10min.length > 0 ||
    props.trajectories10min.length > 0 ||
    props.eventWindows10min.length > 0
)

function toMinutes(bucketStart: string): number {
  const parsed = Date.parse(bucketStart.replace(' ', 'T'))
  return Number.isNaN(parsed) ? NaN : parsed / 60000
}

function timeLabel(bucketStart: string): string {
  // "2026-06-16T10:20:00" -> "10:20"
  const match = /T(\d{2}:\d{2})/.exec(bucketStart)
  return match ? match[1] : bucketStart
}

function subscript(n: number): string {
  const map: Record<string, string> = {
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉'
  }
  return String(n).split('').map((c) => map[c] ?? c).join('')
}

// --- Derived: missing 10-minute windows across observed state vectors --------
const missingWindowCount = computed(() => {
  const byService = new Map<string, number[]>()
  for (const v of props.stateVectors10min) {
    const m = toMinutes(v.bucket_start)
    if (Number.isNaN(m)) continue
    const arr = byService.get(v.service_name) ?? []
    arr.push(m)
    byService.set(v.service_name, arr)
  }
  let missing = 0
  for (const arr of byService.values()) {
    arr.sort((a, b) => a - b)
    for (let i = 1; i < arr.length; i += 1) {
      const gap = arr[i] - arr[i - 1]
      if (gap > BUCKET_STEP_MINUTES) {
        missing += Math.round(gap / BUCKET_STEP_MINUTES) - 1
      }
    }
  }
  return missing
})

const composableTrajectories = computed(() =>
  props.trajectories10min.filter((t) => (t.window_length ?? 0) >= props.windowLength)
)

// State-vector lookup by id and by (service, minute) for target discovery.
const vectorById = computed(() => {
  const map = new Map<string, SystemStateVector>()
  for (const v of props.stateVectors10min) map.set(v.vector_id, v)
  return map
})

const vectorByServiceMinute = computed(() => {
  const map = new Map<string, SystemStateVector>()
  for (const v of props.stateVectors10min) {
    const m = toMinutes(v.bucket_start)
    if (!Number.isNaN(m)) map.set(`${v.service_name}@${m}`, v)
  }
  return map
})

function targetsAfter(trajectory: Trajectory, count: number): SystemStateVector[] {
  const endMin = toMinutes(trajectory.end_bucket)
  if (Number.isNaN(endMin)) return []
  const out: SystemStateVector[] = []
  for (let i = 1; i <= count; i += 1) {
    const key = `${trajectory.service_name}@${endMin + i * BUCKET_STEP_MINUTES}`
    const found = vectorByServiceMinute.value.get(key)
    if (!found) break
    out.push(found)
  }
  return out
}

const targetCandidateCount = computed(
  () => composableTrajectories.value.filter((t) => targetsAfter(t, 1).length === 1).length
)

// --- Readiness (Derived) ----------------------------------------------------
const readiness = computed<RecFMReadiness>(() => {
  const vectors = props.stateVectors10min
  const dimension = vectors[0]?.vector?.length ?? 0
  const schema = vectors[0]?.feature_schema_version ?? 'system-state-v1'
  const labelDistribution: Record<string, number> = {}
  let withIncident = 0
  for (const v of vectors) {
    labelDistribution[v.label] = (labelDistribution[v.label] ?? 0) + 1
    if (v.incident_id) withIncident += 1
  }
  const services = Array.from(new Set(vectors.map((v) => v.service_name))).filter(Boolean)
  const composable = composableTrajectories.value.length

  const messages: string[] = []
  let level: RecFMReadiness['level']
  if (
    vectors.length === 0 ||
    props.trajectories10min.length === 0 ||
    composable === 0
  ) {
    level = 'insufficient'
    if (vectors.length === 0) messages.push('No 10-minute state vectors.')
    if (props.trajectories10min.length === 0) messages.push('No 10-minute trajectories.')
    if (composable === 0)
      messages.push(`No consecutive ${props.windowLength}-window trajectory.`)
  } else if (withIncident === 0 || targetCandidateCount.value === 0) {
    level = 'partial'
    messages.push('10-minute trajectories exist, but the dataset is not model-ready.')
    if (withIncident === 0) messages.push('No incident_id / explicit target label present.')
    messages.push('No train/validation/test split defined.')
    messages.push('No trained RecFM model.')
  } else {
    level = 'partial'
    messages.push('Trajectory와 미래 시점의 관측 target을 구성할 수 있습니다.')
    messages.push('Still Partial: no trained RecFM model and no train/val/test split.')
  }

  return {
    level,
    requiredBucket: '10min',
    availableBuckets: props.availableBuckets,
    eventWindowCount: props.eventWindows10min.length,
    stateVectorCount: vectors.length,
    trajectoryCount: props.trajectories10min.length,
    trajectoryClusterCount: props.trajectoryClusters10min.length,
    featureSchemaVersion: schema,
    stateVectorDimension: dimension,
    trajectoryWindowLength: props.windowLength,
    observedDurationMinutes: props.windowLength * BUCKET_STEP_MINUTES,
    availableServices: services,
    vectorsWithIncidentIdRatio: vectors.length ? withIncident / vectors.length : 0,
    labelDistribution,
    composableTrajectoryCount: composable,
    targetCandidateCount: targetCandidateCount.value,
    missingWindowCount: missingWindowCount.value,
    messages
  }
})

const readinessBadgeClass = computed(() => {
  switch (readiness.value.level) {
    case 'insufficient':
      return 'bg-rose-100 text-rose-700'
    case 'partial':
      return 'bg-amber-100 text-amber-700'
    default:
      return 'bg-emerald-100 text-emerald-700'
  }
})

// --- Trajectory selection ---------------------------------------------------
const selectedTrajectoryId = computed(() => {
  const chosen = store.selectedRecFMTrajectoryId
  if (chosen && props.trajectories10min.some((t) => t.trajectory_id === chosen)) {
    return chosen
  }
  return composableTrajectories.value[0]?.trajectory_id
    ?? props.trajectories10min[0]?.trajectory_id
    ?? null
})

const selectedTrajectory = computed(
  () => props.trajectories10min.find((t) => t.trajectory_id === selectedTrajectoryId.value) ?? null
)

function onSelectTrajectory(id: string) {
  store.selectedRecFMTrajectoryId = id || null
}

function trajectoryOptionLabel(t: Trajectory): string {
  return `${t.service_name} · ${timeLabel(t.start_bucket)}→${timeLabel(t.end_bucket)} · ${t.window_length}w`
}

// --- Observed steps ---------------------------------------------------------
const observedSteps = computed<RecFMStateStep[]>(() => {
  const t = selectedTrajectory.value
  if (!t) return []
  return t.vector_ids.map((vid, idx) => {
    const v = vectorById.value.get(vid)
    const features = (v?.features ?? {}) as Record<string, number>
    const window = props.eventWindows10min.find(
      (w) => w.service_name === v?.service_name && w.bucket_start === v?.bucket_start
    )
    const topFp = window?.top_fingerprints?.[0]?.fingerprint ?? ''
    return {
      index: idx,
      symbol: `x${subscript(idx)}`,
      bucketStart: v?.bucket_start ?? '',
      timeLabel: v ? timeLabel(v.bucket_start) : '-',
      label: v?.label ?? 'normal',
      totalEvents: Number(features.total_events ?? 0),
      errorRatio: Number(features.error_ratio ?? 0),
      warnRatio: Number(features.warn_ratio ?? 0),
      anomalyCount: Number(features.anomaly_count ?? 0),
      maxRisk: Number(features.max_risk_score ?? 0),
      topFingerprint: topFp,
      dataClass: 'observed'
    }
  })
})

const lastObservedStep = computed(() => observedSteps.value[observedSteps.value.length - 1])

const topFingerprintLabel = computed(
  () => selectedTrajectory.value?.top_fingerprints?.[0]?.fingerprint ?? '-'
)

const historicalTargets = computed(() =>
  selectedTrajectory.value ? targetsAfter(selectedTrajectory.value, 4) : []
)

// --- Horizons ---------------------------------------------------------------
const horizons = computed<RecFMHorizonPreview[]>(() => {
  const t = selectedTrajectory.value
  const enough = (t?.window_length ?? 0) >= props.windowLength
  return [1, 2, 4].map((windows) => {
    const targets = t ? targetsAfter(t, windows) : []
    const historicalTargetsAvailable = targets.length === windows
    const trainingSampleComposable = enough && historicalTargetsAvailable
    const targetSymbols = Array.from({ length: windows }, (_, i) =>
      `x${subscript(props.windowLength + i)}`
    )
    let missingRequirement = ''
    if (!enough) missingRequirement = `input window ${props.windowLength}개 필요`
    else if (!historicalTargetsAvailable)
      missingRequirement = `미래 시점 관측 target window ${windows - targets.length}개 없음`
    return {
      windows,
      horizonMinutes: windows * BUCKET_STEP_MINUTES,
      inputWindows: `[x₀ … x${subscript(props.windowLength - 1)}]`,
      targetSymbols,
      requiredInputWindows: props.windowLength,
      historicalTargetsAvailable,
      trainingSampleComposable,
      status: '학습되지 않음',
      missingRequirement
    }
  })
})

function selectHorizon(windows: number): void {
  store.selectedRecFMHorizon = windows as 1 | 2 | 4
}

function horizonSampleCount(windows: number): number {
  return composableTrajectories.value.filter(
    (t) => targetsAfter(t, windows).length === windows
  ).length
}
function horizonMissingCount(windows: number): number {
  return composableTrajectories.value.length - horizonSampleCount(windows)
}

// --- Conceptual flow path (SVG) ---------------------------------------------
const flowMetric = ref<'totalEvents' | 'errorRatio' | 'anomalyCount' | 'maxRisk'>(
  'totalEvents'
)
const flowW = 640
const flowH = 200
const pad = 28

const flowPoints = computed<RecFMFlowPoint[]>(() => {
  const steps = observedSteps.value
  const n = steps.length
  if (n < 2) return []
  return steps.map((s, idx) => ({
    t: idx / (n - 1),
    totalEvents: s.totalEvents,
    errorRatio: s.errorRatio,
    anomalyCount: s.anomalyCount,
    maxRisk: s.maxRisk,
    dataClass: 'observed'
  }))
})

const flowValues = computed(() => flowPoints.value.map((p) => Number(p[flowMetric.value])))

function flowX(t: number): number {
  return pad + t * (flowW - 2 * pad)
}
function flowY(value: number): number {
  const vals = flowValues.value
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const span = max - min || 1
  return flowH - pad - ((value - min) / span) * (flowH - 2 * pad)
}

const observedPolyline = computed(() =>
  flowPoints.value
    .map((p, idx) => `${flowX(p.t)},${flowY(flowValues.value[idx])}`)
    .join(' ')
)

// --- Label / roadmap --------------------------------------------------------
function labelClass(label: string): string {
  if (label === 'incident') return 'bg-rose-100 text-rose-700'
  if (label === 'warning') return 'bg-amber-100 text-amber-700'
  return 'bg-slate-100 text-slate-600'
}

const roadmap = [
  {
    title: 'Phase 1 — 현재',
    current: true,
    items: [
      '10min window 집계',
      'trajectory 점검',
      '데이터 준비도',
      'input/target 구성 미리보기',
      'recursive horizon 미리보기',
      '개념적 flow path'
    ]
  },
  {
    title: 'Phase 2 — Dataset',
    current: false,
    items: [
      'incident 경계 라벨링',
      'incident_id 할당',
      'train/validation/test 분할',
      'multi-horizon sample 생성',
      '정규화 및 feature schema 고정',
      '누락 window 처리 정책'
    ]
  },
  {
    title: 'Phase 3 — Model',
    current: false,
    items: [
      'RecFM 학습',
      'self-consistency 목표',
      'checkpoint/version 관리',
      'offline 평가',
      'baseline 비교'
    ]
  },
  {
    title: 'Phase 4 — Inference',
    current: false,
    items: [
      '현재 상태 input',
      '미래 trajectory 생성',
      'multi-horizon 일관성',
      '가장 유사한 incident pattern 비교',
      '불확실성 및 조기 경보'
    ]
  }
]
</script>
