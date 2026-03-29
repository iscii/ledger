<script setup lang="ts">
import type { ActionDiff } from '../types'

defineProps<{ diff: ActionDiff }>()

function renderValue(v: unknown): string {
  if (v === null || v === undefined) return 'null'
  if (typeof v === 'string') return v
  return JSON.stringify(v)
}

type ChangeEntry = { key: string; from: unknown; to: unknown }

function getChanges(changes: Record<string, unknown>): ChangeEntry[] {
  const entries: ChangeEntry[] = []
  for (const [field, change] of Object.entries(changes)) {
    const c = change as { from: Record<string, unknown>; to: Record<string, unknown> }
    // Flatten one level: show args.path, result.content etc.
    const fromKeys = new Set([...Object.keys(c.from ?? {}), ...Object.keys(c.to ?? {})])
    if (fromKeys.size === 0) {
      entries.push({ key: field, from: c.from, to: c.to })
    } else {
      for (const k of fromKeys) {
        const fv = (c.from ?? {})[k]
        const tv = (c.to ?? {})[k]
        if (JSON.stringify(fv) !== JSON.stringify(tv)) {
          entries.push({ key: `${field}.${k}`, from: fv, to: tv })
        }
      }
    }
  }
  return entries
}
</script>

<template>
  <div class="diff-row" :class="diff.kind">
    <div class="row-main">
      <span class="prefix" :class="diff.kind">{{
        diff.kind === 'same' ? '=' :
        diff.kind === 'changed' ? '~' :
        diff.kind === 'added' ? '+' : '-'
      }}</span>
      <span class="seq">#{{ diff.seq }}</span>
      <span class="tool">{{ diff.tool }}</span>
      <span v-if="diff.kind === 'added'" class="side-note">(only in B)</span>
      <span v-else-if="diff.kind === 'removed'" class="side-note">(only in A)</span>
    </div>

    <div v-if="diff.kind === 'changed'" class="changes">
      <div
        v-for="entry in getChanges(diff.changes as Record<string, unknown>)"
        :key="entry.key"
        class="change-line"
      >
        <span class="change-key">{{ entry.key }}:</span>
        <span class="change-from">{{ renderValue(entry.from) }}</span>
        <span class="change-arrow">→</span>
        <span class="change-to">{{ renderValue(entry.to) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.diff-row {
  padding: 5px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}

.diff-row.same {
  background: transparent;
}

.diff-row.changed {
  background: rgba(210, 153, 34, 0.08);
}

.diff-row.added {
  background: rgba(63, 185, 80, 0.08);
}

.diff-row.removed {
  background: rgba(248, 81, 73, 0.08);
}

.row-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.prefix {
  font-family: var(--font-mono);
  font-size: 13px;
  font-weight: 700;
  width: 14px;
  flex-shrink: 0;
}

.prefix.same    { color: var(--text-muted); }
.prefix.changed { color: var(--amber); }
.prefix.added   { color: var(--green); }
.prefix.removed { color: var(--red); }

.seq {
  font-family: var(--font-mono);
  color: var(--text-muted);
  font-size: 11px;
  min-width: 28px;
}

.tool {
  font-family: var(--font-mono);
  color: var(--text);
}

.side-note {
  font-size: 11px;
  color: var(--text-muted);
  font-style: italic;
}

.changes {
  margin-top: 3px;
  padding-left: 22px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.change-line {
  display: flex;
  align-items: baseline;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 11px;
  flex-wrap: wrap;
}

.change-key {
  color: var(--text-muted);
}

.change-from {
  color: var(--red);
  text-decoration: line-through;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.change-arrow {
  color: var(--text-muted);
}

.change-to {
  color: var(--green);
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
