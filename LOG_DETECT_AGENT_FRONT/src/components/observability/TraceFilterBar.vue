<template>
  <section class="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
    <div class="flex flex-wrap items-end gap-2">
      <label class="flex flex-col gap-0.5">
        <span class="text-[10px] font-semibold uppercase text-slate-400">검색</span>
        <input
          type="search"
          :value="searchText"
          placeholder="제목 · Tool · fingerprint · request"
          class="w-56 rounded border border-slate-300 px-2 py-1 text-sm"
          @input="emit('update:searchText', ($event.target as HTMLInputElement).value)"
        />
      </label>

      <label class="flex flex-col gap-0.5">
        <span class="text-[10px] font-semibold uppercase text-slate-400">이벤트 유형</span>
        <select
          :value="selectedKind"
          class="rounded border border-slate-300 px-2 py-1 text-sm"
          @change="emit('update:selectedKind', ($event.target as HTMLSelectElement).value)"
        >
          <option value="all">전체</option>
          <option v-for="option in kindOptions" :key="option.value" :value="option.value">
            {{ option.label }}
          </option>
        </select>
      </label>

      <label class="flex flex-col gap-0.5">
        <span class="text-[10px] font-semibold uppercase text-slate-400">상태</span>
        <select
          :value="selectedStatus"
          class="rounded border border-slate-300 px-2 py-1 text-sm"
          @change="emit('update:selectedStatus', ($event.target as HTMLSelectElement).value)"
        >
          <option value="all">전체</option>
          <option value="planned">계획됨</option>
          <option value="running">실행 중</option>
          <option value="completed">완료</option>
          <option value="failed">실패</option>
          <option value="skipped">건너뜀</option>
        </select>
      </label>

      <label class="flex flex-col gap-0.5">
        <span class="text-[10px] font-semibold uppercase text-slate-400">Agent</span>
        <select
          :value="selectedAgent"
          class="rounded border border-slate-300 px-2 py-1 text-sm"
          @change="emit('update:selectedAgent', ($event.target as HTMLSelectElement).value)"
        >
          <option value="all">전체</option>
          <option v-for="agent in agents" :key="agent" :value="agent">{{ agent }}</option>
        </select>
      </label>

      <label class="flex flex-col gap-0.5">
        <span class="text-[10px] font-semibold uppercase text-slate-400">외부 의존성</span>
        <select
          :value="selectedDep"
          class="rounded border border-slate-300 px-2 py-1 text-sm"
          @change="emit('update:selectedDep', ($event.target as HTMLSelectElement).value)"
        >
          <option value="all">전체</option>
          <option v-for="dep in depOptions" :key="dep.value" :value="dep.value">
            {{ dep.label }}
          </option>
        </select>
      </label>

      <label
        class="flex cursor-pointer items-center gap-1.5 rounded border border-slate-300 px-2 py-1.5 text-sm"
        :class="failuresOnly ? 'bg-red-50 text-red-700' : 'text-slate-600'"
      >
        <input
          type="checkbox"
          :checked="failuresOnly"
          @change="emit('update:failuresOnly', ($event.target as HTMLInputElement).checked)"
        />
        실패·재시도만
      </label>

      <button
        type="button"
        class="ml-auto rounded border border-slate-300 px-2 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
        @click="emit('reset')"
      >
        필터 초기화
      </button>
    </div>
  </section>
</template>

<script setup lang="ts">
import {
  DEPENDENCY_FILTERS,
  KIND_FILTER_OPTIONS
} from '@/components/observability/observability'

defineProps<{
  searchText: string
  selectedKind: string
  selectedStatus: string
  selectedAgent: string
  selectedDep: string
  failuresOnly: boolean
  agents: string[]
}>()

const emit = defineEmits<{
  (event: 'update:searchText', value: string): void
  (event: 'update:selectedKind', value: string): void
  (event: 'update:selectedStatus', value: string): void
  (event: 'update:selectedAgent', value: string): void
  (event: 'update:selectedDep', value: string): void
  (event: 'update:failuresOnly', value: boolean): void
  (event: 'reset'): void
}>()

const kindOptions = KIND_FILTER_OPTIONS
const depOptions = DEPENDENCY_FILTERS
</script>
