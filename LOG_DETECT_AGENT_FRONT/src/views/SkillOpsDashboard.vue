<template>
  <AppLayout>
    <template #header-right>
      <div class="flex items-center gap-3">
        <button
          class="rounded border border-slate-300 bg-white px-3 py-2 text-sm hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="store.loadingPatternOpsSkills"
          @click="store.fetchPatternOpsSkills"
        >
          Refresh Registry
        </button>
        <div class="text-right text-xs text-slate-600">
          <p>Registered: {{ store.patternOpsSkills.length }}</p>
          <p>Edges: {{ store.patternOpsSkillEdges.length }}</p>
        </div>
      </div>
    </template>

    <section class="grid grid-cols-2 gap-3 text-sm lg:grid-cols-4">
      <OverviewCard
        label="Registered Skills"
        :value="store.patternOpsSkills.length"
      />
      <OverviewCard
        label="Registry Edges"
        :value="store.patternOpsSkillEdges.length"
      />
      <OverviewCard
        label="Execution Success"
        :value="store.skillOpsOverview.success"
        :subtitle="`${store.skillOpsOverview.selected} selected`"
      />
      <OverviewCard
        label="Selected Only"
        :value="store.skillOpsOverview.selectedOnly"
        :subtitle="`${store.skillOpsOverview.failed} failed`"
      />
    </section>

    <PatternOpsSkillExecutionPanel
      :executions="store.patternOpsSkillExecutions"
      :plan="store.patternOpsSkillPlan"
      :skills="store.patternOpsSkills"
      :edges="store.patternOpsSkillEdges"
      :validator-results="store.patternOpsValidatorResults"
      :loading="store.loadingPatternOpsSkills"
      @refresh="store.fetchPatternOpsSkills"
    />

    <section class="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <h2 class="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
        Skill Execution Timeline
      </h2>
      <AgentProgressTimeline
        :steps="store.agentTimeline"
        :skill-executions="store.patternOpsSkillExecutions"
      />
    </section>
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import AppLayout from '@/components/layout/AppLayout.vue'
import OverviewCard from '@/components/dashboard/OverviewCard.vue'
import PatternOpsSkillExecutionPanel from '@/components/dashboard/PatternOpsSkillExecutionPanel.vue'
import AgentProgressTimeline from '@/components/dashboard/AgentProgressTimeline.vue'
import { useLogDetectStore } from '@/stores/logDetectStore'

const store = useLogDetectStore()

onMounted(async () => {
  await store.fetchPatternOpsSkills()
})
</script>
