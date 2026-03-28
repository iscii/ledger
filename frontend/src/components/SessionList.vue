<script setup lang="ts">
import type { Session } from '../types'

defineProps<{
  sessions: Session[]
  selected: string | null
  loading: boolean
}>()

defineEmits<{
  select: [id: string]
}>()

function timeAgo(ts: string): string {
  const diff = Math.floor((Date.now() - new Date(ts).getTime()) / 1000)
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}
</script>

<template>
  <div class="session-list">
    <div class="list-header">
      <span class="title">Sessions</span>
      <span v-if="loading" class="loading-dot">●</span>
    </div>

    <div v-if="sessions.length === 0 && !loading" class="empty">
      No sessions yet.<br />
      Run an agent with Backstep to get started.
    </div>

    <div
      v-for="s in sessions"
      :key="s.session_id"
      class="session-row"
      :class="{ selected: selected === s.session_id }"
      @click="$emit('select', s.session_id)"
    >
      <div class="session-id">{{ s.session_id }}</div>
      <div class="session-meta">
        <span>{{ s.action_count }} action{{ s.action_count !== 1 ? 's' : '' }}</span>
        <span class="dot">·</span>
        <span>{{ timeAgo(s.last_action_at) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-list {
  width: 300px;
  min-width: 300px;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.list-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-weight: 600;
  font-size: 12px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--text-muted);
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.loading-dot {
  color: var(--accent);
  font-size: 10px;
  animation: pulse 1.2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.empty {
  padding: 24px 16px;
  color: var(--text-muted);
  font-size: 12px;
  line-height: 1.7;
}

.session-row {
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background 0.1s;
}

.session-row:hover {
  background: var(--bg-hover);
}

.session-row.selected {
  background: var(--bg-selected);
  border-left-color: var(--accent);
}

.session-id {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--text);
  margin-bottom: 2px;
}

.session-meta {
  font-size: 11px;
  color: var(--text-muted);
  display: flex;
  gap: 4px;
}

.dot {
  color: var(--border);
}
</style>
