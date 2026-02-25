import { createRouter, createWebHistory } from 'vue-router'
import LogDetectDashboard from '@/views/LogDetectDashboard.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'dashboard',
      component: LogDetectDashboard
    }
  ]
})

export default router
