import { createRouter, createWebHistory } from 'vue-router'
import AgentObservabilityDashboard from '@/views/AgentObservabilityDashboard.vue'
import LogDetectDashboard from '@/views/LogDetectDashboard.vue'
import SkillOpsDashboard from '@/views/SkillOpsDashboard.vue'
import TrajectoryDashboard from '@/views/TrajectoryDashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: LogDetectDashboard
    },
    {
      path: '/trajectory',
      name: 'trajectory',
      component: TrajectoryDashboard
    },
    {
      path: '/skills',
      name: 'skills',
      component: SkillOpsDashboard
    },
    {
      path: '/agent-observability',
      name: 'agent-observability',
      component: AgentObservabilityDashboard
    }
  ]
})

export default router
