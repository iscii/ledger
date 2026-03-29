<script setup lang="ts">
import { ref, onMounted, onUnmounted, watch } from 'vue'
import type { Session, SessionDetail } from './types'
import { api } from './api'
import SessionList from './components/SessionList.vue'
import ActionTimeline from './components/ActionTimeline.vue'

const sessions = ref<Session[]>([])
const selectedId = ref<string | null>(null)
const detail = ref<SessionDetail | null>(null)
const sessionsLoading = ref(false)
const detailLoading = ref(false)

async function loadSessions() {
  sessionsLoading.value = true
  try {
    sessions.value = await api.getSessions()
  } catch {
    // silently ignore — server may not be running yet
  } finally {
    sessionsLoading.value = false
  }
}

async function loadDetail(id: string) {
  detailLoading.value = true
  detail.value = null
  try {
    detail.value = await api.getSession(id)
  } finally {
    detailLoading.value = false
  }
}

watch(selectedId, (id) => {
  if (id) loadDetail(id)
  else detail.value = null
})

// Auto-refresh sessions list every 5 seconds
let timer: ReturnType<typeof setInterval>
onMounted(() => {
  loadSessions()
  timer = setInterval(loadSessions, 5000)
})
onUnmounted(() => clearInterval(timer))

function onSelect(id: string) {
  selectedId.value = id
}

function onRefresh() {
  loadSessions()
  if (selectedId.value) loadDetail(selectedId.value)
}
</script>

<template>
  <div class="app">
    <header class="app-header">
      <span class="logo">⏺ Backstep</span>
      <span class="subtitle">AI agent action log</span>
    </header>
    <div class="app-body">
      <SessionList
        :sessions="sessions"
        :selected="selectedId"
        :loading="sessionsLoading"
        @select="onSelect"
      />
      <ActionTimeline
        :detail="detail"
        :loading="detailLoading"
        @refresh="onRefresh"
      />
    </div>
  </div>
</template>

<style scoped>
.app {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.app-header {
  height: 44px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 16px;
  gap: 12px;
  flex-shrink: 0;
  background: var(--bg-panel);
}

.logo {
  font-weight: 700;
  font-size: 14px;
  color: var(--accent);
  letter-spacing: -0.01em;
}

.subtitle {
  font-size: 11px;
  color: var(--text-muted);
}

.app-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}
</style>
