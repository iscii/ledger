<script setup lang="ts">
import { ref } from 'vue'
import type { SessionDetail, RollbackResult, ReplayResult } from '../types'
import { api } from '../api'
import ActionRow from './ActionRow.vue'

const props = defineProps<{ detail: SessionDetail | null; loading: boolean; showCompare?: boolean }>()
const emit = defineEmits<{ refresh: []; compare: [] }>()

const opLoading = ref(false)
const message = ref<{ kind: 'success' | 'error'; text: string } | null>(null)

function formatDate(ts: string): string {
  return new Date(ts).toLocaleString('en-US', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hour12: false,
  })
}

async function runOp(op: () => Promise<RollbackResult | ReplayResult>) {
  if (!props.detail) return
  opLoading.value = true
  message.value = null
  try {
    const result = await op()
    if ('rolled_back' in result) {
      const r = result as RollbackResult
      message.value = {
        kind: r.errors.length ? 'error' : 'success',
        text: `Rolled back ${r.rolled_back.length}, skipped ${r.skipped.length}, errors ${r.errors.length}`,
      }
    } else {
      const r = result as ReplayResult
      message.value = {
        kind: r.errors.length ? 'error' : 'success',
        text: `Replayed ${r.replayed} action${r.replayed !== 1 ? 's' : ''}${r.errors.length ? `, ${r.errors.length} error(s)` : ''}`,
      }
    }
  } catch (e) {
    message.value = { kind: 'error', text: String(e) }
  } finally {
    opLoading.value = false
    emit('refresh')
  }
}
</script>

<template>
  <div class="timeline">
    <!-- Empty state -->
    <div v-if="!detail && !loading" class="empty">
      <div class="empty-icon">⏺</div>
      <div class="empty-text">Select a session to inspect its action log.</div>
    </div>

    <!-- Loading -->
    <div v-else-if="loading" class="empty">
      <div class="empty-text muted">Loading…</div>
    </div>

    <!-- Session detail -->
    <template v-else-if="detail">
      <div class="timeline-header">
        <div class="header-info">
          <span class="session-id">{{ detail.session_id }}</span>
          <span class="meta">
            {{ detail.actions.length }} action{{ detail.actions.length !== 1 ? 's' : '' }}
            · started {{ detail.actions.length ? formatDate(detail.actions[0].ts) : '—' }}
          </span>
        </div>
        <div class="header-actions">
          <span v-if="message" class="op-message" :class="message.kind">{{ message.text }}</span>
          <button v-if="props.showCompare" @click="emit('compare')">Compare</button>
          <button :disabled="opLoading" @click="runOp(() => api.rollback(detail!.session_id))">
            Rollback
          </button>
          <button :disabled="opLoading" @click="runOp(() => api.replay(detail!.session_id))">
            Replay
          </button>
        </div>
      </div>

      <div class="actions-list">
        <ActionRow
          v-for="action in detail.actions"
          :key="action.id"
          :action="action"
        />
        <div v-if="detail.actions.length === 0" class="empty-actions">
          No actions recorded in this session.
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.timeline {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-muted);
}

.empty-icon {
  font-size: 32px;
  opacity: 0.3;
}

.empty-text {
  font-size: 13px;
}

.muted {
  color: var(--text-muted);
}

.timeline-header {
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-shrink: 0;
}

.header-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.session-id {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

.meta {
  font-size: 11px;
  color: var(--text-muted);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.op-message {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius);
}

.op-message.success {
  color: var(--green);
  background: rgba(63, 185, 80, 0.1);
  border: 1px solid rgba(63, 185, 80, 0.2);
}

.op-message.error {
  color: var(--red);
  background: rgba(248, 81, 73, 0.1);
  border: 1px solid rgba(248, 81, 73, 0.2);
}

.actions-list {
  flex: 1;
  overflow-y: auto;
}

.empty-actions {
  padding: 24px 16px;
  color: var(--text-muted);
  font-size: 12px;
}
</style>
