<template>
  <div class="rounded-xl border bg-white p-4 shadow-sm">
    <p class="text-xs font-medium uppercase text-slate-500">{{ label }}</p>
    <p class="mt-2 text-2xl font-semibold text-slate-900">{{ value }}</p>
    <p v-if="subtitle" class="mt-1 text-xs text-slate-500">{{ subtitle }}</p>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  label: string
  value: string | number
  subtitle?: string
}>()
</script>
