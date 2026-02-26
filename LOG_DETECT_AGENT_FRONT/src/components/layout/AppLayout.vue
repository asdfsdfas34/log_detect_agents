<template>
  <div class="min-h-screen bg-slate-50">
    <header class="sticky top-0 z-30 border-b bg-white/95 backdrop-blur">
      <div class="mx-auto flex max-w-7xl items-center justify-between px-6 py-4">
        <div>
          <p class="text-xs font-medium uppercase tracking-wider text-slate-500">Enterprise Monitoring</p>
          <h1 class="text-xl font-semibold text-slate-900">LogDetect Dashboard</h1>
        </div>
        <slot name="header-right" />
      </div>
    </header>
    <main class="mx-auto max-w-7xl space-y-6 px-6 py-6">
      <slot />
    </main>
  </div>
</template>
