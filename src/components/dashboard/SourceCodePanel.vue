<template>
  <details class="rounded-xl border bg-white p-4 shadow-sm" open>
    <summary class="cursor-pointer text-lg font-semibold">Source Code Analysis</summary>
    <div class="mt-3 space-y-3 text-sm">
      <div v-for="trace in stackTraces" :key="trace" class="rounded border bg-slate-50 p-3">
        <p class="font-mono text-xs text-slate-600">{{ trace }}</p>
        <p class="mt-2">File path: app/services/payment_auth_*.py</p>
        <p>Module: app.services</p>
        <p>Function: process_request</p>
      </div>
    </div>
  </details>
</template>

<script setup lang="ts">
defineProps<{ stackTraces: string[] }>()
</script>
