<template>
  <section class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
    <div class="mb-4 flex items-center justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold uppercase tracking-wide text-slate-500">
          PatternOps Skill Execution
        </h2>
        <p class="mt-1 text-xs text-slate-500">
          {{ executions.length }} execution records · {{ skills.length }} registered skills
        </p>
      </div>
      <button
        class="rounded border border-slate-300 bg-white px-3 py-2 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="loading"
        @click="emit('refresh')"
      >
        Refresh
      </button>
    </div>

    <div class="grid grid-cols-2 gap-3 text-sm lg:grid-cols-4">
      <div class="rounded border border-slate-200 p-3">
        <p class="text-xs font-medium uppercase text-slate-500">Selected</p>
        <p class="mt-1 text-xl font-semibold text-slate-900">
          {{ summary.selected }}
        </p>
      </div>
      <div class="rounded border border-green-200 bg-green-50 p-3">
        <p class="text-xs font-medium uppercase text-green-700">Success</p>
        <p class="mt-1 text-xl font-semibold text-green-800">
          {{ summary.success }}
        </p>
      </div>
      <div class="rounded border border-amber-200 bg-amber-50 p-3">
        <p class="text-xs font-medium uppercase text-amber-700">Selected Only</p>
        <p class="mt-1 text-xl font-semibold text-amber-800">
          {{ summary.selectedOnly }}
        </p>
      </div>
      <div class="rounded border border-red-200 bg-red-50 p-3">
        <p class="text-xs font-medium uppercase text-red-700">Failed</p>
        <p class="mt-1 text-xl font-semibold text-red-800">
          {{ summary.failed }}
        </p>
      </div>
    </div>

    <div v-if="agentGroups.length" class="mt-4 overflow-x-auto">
      <table class="min-w-full divide-y divide-slate-200 text-sm">
        <thead class="bg-slate-50 text-left text-xs uppercase text-slate-500">
          <tr>
            <th class="px-3 py-2 font-semibold">Agent / Scope</th>
            <th class="px-3 py-2 font-semibold">Skill</th>
            <th class="px-3 py-2 font-semibold">Status</th>
            <th class="px-3 py-2 font-semibold">Score</th>
            <th class="px-3 py-2 font-semibold">Reason</th>
          </tr>
        </thead>
        <tbody class="divide-y divide-slate-100">
          <tr v-for="item in flattenedExecutions" :key="item.execution_id">
            <td class="px-3 py-2">
              <p class="font-medium text-slate-900">{{ item.agent_name || '-' }}</p>
              <p class="text-xs text-slate-500">{{ item.scope || '-' }}</p>
            </td>
            <td class="px-3 py-2">
              <p class="font-medium text-slate-800">{{ skillName(item.skill_id) }}</p>
              <p class="text-xs text-slate-500">{{ item.skill_id }}</p>
            </td>
            <td class="px-3 py-2">
              <span
                class="rounded px-2 py-1 text-xs font-semibold uppercase"
                :class="statusClass(item.status)"
              >
                {{ item.status }}
              </span>
            </td>
            <td class="px-3 py-2 text-slate-700">
              {{ formatScore(item.score) }}
            </td>
            <td class="max-w-md px-3 py-2 text-xs text-slate-600">
              {{ item.reason || '-' }}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-else class="mt-4 rounded border border-dashed border-slate-300 p-5 text-center text-sm text-slate-500">
      No PatternOps skill executions yet.
    </div>

    <div class="mt-4 grid gap-3 lg:grid-cols-2">
      <div class="rounded border border-slate-200 p-3">
        <h3 class="mb-2 text-xs font-semibold uppercase text-slate-500">
          Scoped Plans
        </h3>
        <div v-if="scopedPlans.length" class="space-y-2">
          <div
            v-for="plan in scopedPlans"
            :key="plan.scope"
            class="rounded bg-slate-50 p-2"
          >
            <div class="flex items-center justify-between gap-2">
              <span class="text-sm font-medium text-slate-800">
                {{ plan.agentName || plan.scope }}
              </span>
              <span class="text-xs text-slate-500">{{ plan.scope }}</span>
            </div>
            <div class="mt-2 flex flex-wrap gap-1">
              <span
                v-for="skill in plan.skills"
                :key="`${plan.scope}-${skill.skill_id}`"
                class="rounded bg-white px-2 py-1 text-xs text-slate-700 ring-1 ring-slate-200"
              >
                {{ skill.skill_id }}
              </span>
            </div>
          </div>
        </div>
        <p v-else class="text-sm text-slate-500">No scoped plan data.</p>
      </div>

      <div class="rounded border border-slate-200 p-3">
        <h3 class="mb-2 text-xs font-semibold uppercase text-slate-500">
          Registry Edges
        </h3>
        <div v-if="edges.length" class="max-h-48 space-y-2 overflow-y-auto">
          <div
            v-for="edge in edges"
            :key="edge.edge_id"
            class="rounded bg-slate-50 p-2 text-xs text-slate-700"
          >
            <span class="font-medium">{{ edge.from_skill_id }}</span>
            <span class="mx-1 text-slate-400">→</span>
            <span class="font-medium">{{ edge.to_skill_id }}</span>
            <span class="ml-2 rounded bg-white px-1.5 py-0.5 uppercase text-slate-500">
              {{ edge.edge_type }}
            </span>
          </div>
        </div>
        <p v-else class="text-sm text-slate-500">No registry edge data.</p>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type {
  PatternOpsSkill,
  PatternOpsSkillEdge,
  PatternOpsSkillExecution,
  PatternOpsSkillPlan
} from '@/types/agentTypes'

const props = defineProps<{
  executions: PatternOpsSkillExecution[]
  plan: PatternOpsSkillPlan | null
  skills: PatternOpsSkill[]
  edges: PatternOpsSkillEdge[]
  loading?: boolean
}>()

const emit = defineEmits<{
  refresh: []
}>()

const flattenedExecutions = computed(() =>
  [...props.executions].sort((a, b) =>
    `${a.agent_name}:${a.scope}:${a.skill_id}`.localeCompare(
      `${b.agent_name}:${b.scope}:${b.skill_id}`
    )
  )
)

const agentGroups = computed(() => {
  const groups = new Set(
    props.executions.map((item) => `${item.agent_name}:${item.scope}`)
  )
  return [...groups]
})

const summary = computed(() => {
  const selected = new Set(props.executions.map((item) => item.skill_id)).size
  return {
    selected,
    success: props.executions.filter((item) => item.status === 'success').length,
    failed: props.executions.filter((item) => item.status === 'failed').length,
    selectedOnly: props.executions.filter((item) =>
      ['selected', 'planned'].includes(item.status)
    ).length
  }
})

const scopedPlans = computed(() => {
  const scoped = props.plan?.scoped_plans ?? {}
  return Object.entries(scoped).map(([scope, plan]) => ({
    scope,
    agentName: plan.agent_name,
    skills: plan.selected_skills ?? []
  }))
})

function skillName(skillId: string): string {
  return props.skills.find((skill) => skill.skill_id === skillId)?.name ?? skillId
}

function formatScore(score: number): string {
  if (!Number.isFinite(score)) return '-'
  return score.toFixed(2)
}

function statusClass(status: string): string {
  if (status === 'success') return 'bg-green-100 text-green-700'
  if (status === 'failed') return 'bg-red-100 text-red-700'
  if (status === 'selected' || status === 'planned') {
    return 'bg-amber-100 text-amber-700'
  }
  return 'bg-slate-100 text-slate-600'
}
</script>
