<template>
  <div class="flex items-center gap-2 text-sm text-slate-600">
    <div class="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-blue-600" />
    <span>{{ label }}</span>
  </div>
</template>

<script setup lang="ts">
defineProps<{ label?: string }>()
</script>
