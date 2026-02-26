<template>
  <div class="rounded-xl border bg-white p-4 shadow-sm">
    <h3 class="mb-3 text-lg font-semibold">Recommendations</h3>
    <div class="space-y-3">
      <div v-for="item in actions" :key="item.action" class="rounded border p-3">
        <span class="rounded bg-slate-900 px-2 py-1 text-xs text-white">{{ item.priority }}</span>
        <p class="mt-2 text-sm">{{ item.action }}</p>
        <p class="text-xs text-slate-500">Owner: {{ item.owner }}</p>
      </div>
      <pre class="overflow-x-auto rounded bg-slate-900 p-3 text-xs text-slate-100">{{ verificationText }}</pre>
      <button class="rounded bg-blue-600 px-3 py-2 text-sm text-white" @click="copyText">Copy to clipboard</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { RecommendedAction } from '@/types/agentTypes'

const props = defineProps<{ actions: RecommendedAction[]; verification: string[] }>()

const verificationText = computed(() => props.verification.join('\n'))

async function copyText() {
  await navigator.clipboard.writeText(verificationText.value)
}
</script>
