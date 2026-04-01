<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import type { Session, SessionDetail } from './types'
import { api } from './api'
import SessionList from './components/SessionList.vue'
import ActionTimeline from './components/ActionTimeline.vue'
import DiffView from './components/DiffView.vue'

const sessions = ref<Session[]>([])
const selectedId = ref<string | null>(null)
const dbPath = ref<string | null>(null)
const detail = ref<SessionDetail | null>(null)
const sessionsLoading = ref(false)
const detailLoading = ref(false)

// Diff state
const diffSessionId = ref<string | null>(null)
const showDiff = computed(() => diffSessionId.value !== null)
const showPicker = ref(false)

const otherSessions = computed(() =>
  sessions.value.filter(s => s.session_id !== selectedId.value)
)

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
  diffSessionId.value = null
  showPicker.value = false
  if (id) loadDetail(id)
  else detail.value = null
})

// Auto-refresh sessions list every 5 seconds
let timer: ReturnType<typeof setInterval>
onMounted(() => {
  loadSessions()
  timer = setInterval(loadSessions, 5000)
  api.getConfig().then(c => { dbPath.value = c.db_path }).catch(() => {})
})
onUnmounted(() => clearInterval(timer))

function onSelect(id: string) {
  selectedId.value = id
}

function onRefresh() {
  loadSessions()
  if (selectedId.value) loadDetail(selectedId.value)
}

function onPickSession(id: string) {
  diffSessionId.value = id
  showPicker.value = false
}

function closeDiff() {
  diffSessionId.value = null
  showPicker.value = false
}
</script>

<template>
  <div class="app">
    <header class="app-header">
      <span class="logo">⏺ Backstep</span>
      <span class="subtitle">AI agent action log</span>
    </header>
    <div v-if="dbPath" class="app-footer">
      <span class="db-path">Connected to: {{ dbPath }}</span>
    </div>
    <div class="app-body">
      <SessionList
        :sessions="sessions"
        :selected="selectedId"
        :loading="sessionsLoading"
        @select="onSelect"
      />

      <div class="right-panel">
        <!-- Session picker overlay -->
        <div v-if="showPicker" class="picker-overlay">
          <div class="picker-header">
            <span class="picker-title">Pick a session to compare</span>
            <button class="btn-cancel" @click="showPicker = false">Cancel</button>
          </div>
          <div class="picker-list">
            <div
              v-for="s in otherSessions"
              :key="s.session_id"
              class="picker-row"
              @click="onPickSession(s.session_id)"
            >
              <span class="picker-sid">{{ s.session_id }}</span>
              <span class="picker-meta">{{ s.action_count }} actions</span>
            </div>
            <div v-if="otherSessions.length === 0" class="picker-empty">
              No other sessions available.
            </div>
          </div>
        </div>

        <!-- Diff view -->
        <template v-if="showDiff && selectedId">
          <div class="diff-toolbar">
            <span class="diff-label">Comparing sessions</span>
            <button @click="closeDiff">Close diff</button>
          </div>
          <DiffView :session-a="selectedId" :session-b="diffSessionId!" />
        </template>

        <!-- Normal timeline -->
        <template v-else>
          <ActionTimeline
            :detail="detail"
            :loading="detailLoading"
            :show-compare="selectedId !== null"
            @refresh="onRefresh"
            @compare="showPicker = true"
          />
        </template>
      </div>
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

.app-footer {
  height: 24px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 16px;
  flex-shrink: 0;
  background: var(--bg);
}

.db-path {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-muted);
}

.app-body {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.right-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  position: relative;
}

/* Session picker */
.picker-overlay {
  border-bottom: 1px solid var(--border);
  background: var(--bg-panel);
  flex-shrink: 0;
  max-height: 260px;
  display: flex;
  flex-direction: column;
}

.picker-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
}

.picker-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
}

.btn-cancel {
  font-size: 11px;
  padding: 2px 10px;
}

.picker-list {
  overflow-y: auto;
  flex: 1;
}

.picker-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  cursor: pointer;
  border-bottom: 1px solid var(--border);
  transition: background 0.1s;
}

.picker-row:hover {
  background: var(--bg-hover);
}

.picker-sid {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
}

.picker-meta {
  font-size: 11px;
  color: var(--text-muted);
}

.picker-empty {
  padding: 16px;
  font-size: 12px;
  color: var(--text-muted);
}

/* Diff toolbar */
.diff-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  background: var(--bg-panel);
}

.diff-label {
  font-size: 12px;
  color: var(--text-muted);
}
</style>
