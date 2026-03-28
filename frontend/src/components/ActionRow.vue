<script setup lang="ts">
import { ref } from 'vue'
import type { Action } from '../types'
import StatusBadge from './StatusBadge.vue'

const props = defineProps<{ action: Action }>()
const expanded = ref(false)

function formatTs(ts: string): string {
  return new Date(ts).toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
</script>

<template>
  <div class="action-row" :class="{ expanded }" @click="expanded = !expanded">
    <div class="row-header">
      <span class="seq">#{{ action.seq }}</span>
      <span class="tool">{{ action.tool }}</span>
      <StatusBadge :status="action.status" :reversible="action.reversible" />
      <span class="ts">{{ formatTs(action.ts) }}</span>
      <span class="chevron">{{ expanded ? '▾' : '▸' }}</span>
    </div>

    <div v-if="expanded" class="row-detail">
      <div class="detail-line">
        <span class="detail-label">args</span>
        <pre class="json">{{ JSON.stringify(action.args, null, 2) }}</pre>
      </div>
      <div class="detail-line">
        <span class="detail-label">result</span>
        <pre class="json">{{ JSON.stringify(action.result, null, 2) }}</pre>
      </div>
    </div>
  </div>
</template>

<style scoped>
.action-row {
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  transition: background 0.1s;
}

.action-row:hover {
  background: var(--bg-hover);
}

.row-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 16px;
  user-select: none;
}

.seq {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  min-width: 24px;
}

.tool {
  font-family: var(--font-mono);
  font-size: 12px;
  color: var(--accent);
  min-width: 140px;
}

.ts {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-muted);
  margin-left: auto;
}

.chevron {
  color: var(--text-muted);
  font-size: 11px;
  margin-left: 8px;
}

.row-detail {
  padding: 0 16px 12px 50px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.detail-line {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.detail-label {
  color: var(--text-muted);
  font-size: 11px;
  min-width: 36px;
  padding-top: 2px;
}

.json {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 10px;
  margin: 0;
  white-space: pre-wrap;
  word-break: break-all;
  flex: 1;
}
</style>
