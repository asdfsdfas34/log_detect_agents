<template>
  <div
    v-if="store.backendActionPending"
    class="pointer-events-none fixed z-50 flex items-center gap-2 rounded-full border border-slate-200 bg-white/95 px-3 py-2 text-xs font-semibold text-slate-700 shadow-lg"
    :style="indicatorStyle"
    role="status"
    aria-live="polite"
  >
    <span
      class="h-4 w-4 rounded-full border-2 border-slate-200 border-t-blue-600 motion-safe:animate-spin"
      aria-hidden="true"
    />
    <span>{{ store.backendActionLabel || '처리중' }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useLogDetectStore } from '@/stores/logDetectStore'

const store = useLogDetectStore()
const pointerX = ref(24)
const pointerY = ref(24)

const indicatorStyle = computed(() => ({
  left: `${pointerX.value + 14}px`,
  top: `${pointerY.value + 14}px`
}))

function updatePointer(event: PointerEvent) {
  pointerX.value = event.clientX
  pointerY.value = event.clientY
}

onMounted(() => {
  window.addEventListener('pointermove', updatePointer, { passive: true })
})

onBeforeUnmount(() => {
  window.removeEventListener('pointermove', updatePointer)
})
</script>
