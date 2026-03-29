<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import type { DiffResult } from '../types'
import { api } from '../api'
import DiffRow from './DiffRow.vue'

const props = defineProps<{ sessionA: string; sessionB: string }>()

const result = ref<DiffResult | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

async function load() {
  loading.value = true
  error.value = null
  result.value = null
  try {
    result.value = await api.getDiff(props.sessionA, props.sessionB)
  } catch (e) {
    error.value = String(e)
  } finally {
    loading.value = false
  }
}

watch(() => [props.sessionA, props.sessionB], load, { immediate: true })

const countA = computed(() => {
  if (!result.value) return 0
  return result.value.actions.filter(a => a.action_a !== null).length
})

const countB = computed(() => {
  if (!result.value) return 0
  return result.value.actions.filter(a => a.action_b !== null).length
})

const summary = computed(() => {
  if (!result.value) return null
  const actions = result.value.actions
  const same = actions.filter(a => a.kind === 'same').length
  const changed = actions.filter(a => a.kind === 'changed').length
  const added = actions.filter(a => a.kind === 'added').length
  const removed = actions.filter(a => a.kind === 'removed').length
  return { same, changed, added, removed }
})

const identical = computed(() =>
  result.value !== null && result.value.actions.every(a => a.kind === 'same')
)
</script>

<template>
  <div class="diff-view">
    <div v-if="loading" class="state-msg">Loading diff…</div>
    <div v-else-if="error" class="state-msg error">{{ error }}</div>

    <template v-else-if="result">
      <!-- Column headers -->
      <div class="diff-header">
        <div class="col-a">
          <span class="sid">{{ result.session_a }}</span>
          <span class="count">{{ countA }} action{{ countA !== 1 ? 's' : '' }}</span>
        </div>
        <div class="legend">
          <span class="leg same">= same</span>
          <span class="leg changed">~ changed</span>
          <span class="leg added">+ added</span>
          <span class="leg removed">- removed</span>
        </div>
        <div class="col-b">
          <span class="sid">{{ result.session_b }}</span>
          <span class="count">{{ countB }} action{{ countB !== 1 ? 's' : '' }}</span>
        </div>
      </div>

      <!-- Identical notice -->
      <div v-if="identical" class="identical-msg">
        Sessions are identical — no differences found.
      </div>

      <!-- Rows -->
      <div v-else class="diff-rows">
        <DiffRow v-for="(d, i) in result.actions" :key="i" :diff="d" />
      </div>

      <!-- Summary -->
      <div v-if="summary" class="diff-summary">
        <span class="sum same">{{ summary.same }} same</span>
        <span class="sep">·</span>
        <span class="sum changed">{{ summary.changed }} changed</span>
        <span class="sep">·</span>
        <span class="sum added">{{ summary.added }} added</span>
        <span class="sep">·</span>
        <span class="sum removed">{{ summary.removed }} removed</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
.diff-view {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  flex: 1;
}

.state-msg {
  padding: 24px 16px;
  color: var(--text-muted);
  font-size: 12px;
}

.state-msg.error {
  color: var(--red);
}

.diff-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 16px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  gap: 12px;
}

.col-a,
.col-b {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.col-b {
  text-align: right;
  align-items: flex-end;
}

.sid {
  font-family: var(--font-mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 180px;
}

.count {
  font-size: 11px;
  color: var(--text-muted);
}

.legend {
  display: flex;
  gap: 10px;
  flex-shrink: 0;
}

.leg {
  font-family: var(--font-mono);
  font-size: 11px;
}

.leg.same    { color: var(--text-muted); }
.leg.changed { color: var(--amber); }
.leg.added   { color: var(--green); }
.leg.removed { color: var(--red); }

.identical-msg {
  padding: 32px 16px;
  color: var(--text-muted);
  font-size: 12px;
  text-align: center;
}

.diff-rows {
  flex: 1;
  overflow-y: auto;
}

.diff-summary {
  padding: 8px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  flex-shrink: 0;
  background: var(--bg-panel);
}

.sep {
  color: var(--text-muted);
}

.sum.same    { color: var(--text-muted); }
.sum.changed { color: var(--amber); }
.sum.added   { color: var(--green); }
.sum.removed { color: var(--red); }
</style>
