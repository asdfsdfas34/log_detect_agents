<template>
  <div class="space-y-2 text-sm text-slate-600">
    <div class="flex items-center gap-2">
      <div
        class="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600"
      />
      <span>{{ label }}</span>
    </div>
    <div
      v-if="stageLog"
      class="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-700"
      aria-live="polite"
    >
      {{ stageLog }}
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ label?: string; stageLog?: string }>()
</script>
