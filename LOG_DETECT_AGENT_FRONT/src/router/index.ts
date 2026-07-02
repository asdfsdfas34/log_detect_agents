import { createRouter, createWebHistory } from 'vue-router'
import LogDetectDashboard from '@/views/LogDetectDashboard.vue'
import SkillOpsDashboard from '@/views/SkillOpsDashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: LogDetectDashboard
    },
    {
      path: '/skills',
      name: 'skills',
      component: SkillOpsDashboard
    }
  ]
})

export default router
