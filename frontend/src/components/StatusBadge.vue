<script setup lang="ts">
defineProps<{
  status: 'ok' | 'error' | 'committed'
  reversible: boolean
}>()
</script>

<template>
  <span class="badges">
    <span class="badge" :class="status">{{ status }}</span>
    <span v-if="reversible" class="badge reversible">reversible</span>
    <span v-if="status === 'committed'" class="badge committed-lock">⚑ irreversible</span>
  </span>
</template>

<style scoped>
.badges {
  display: inline-flex;
  gap: 4px;
  align-items: center;
}

.badge {
  display: inline-block;
  padding: 1px 7px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.02em;
}

.badge.ok {
  background: rgba(63, 185, 80, 0.15);
  color: var(--green);
  border: 1px solid rgba(63, 185, 80, 0.3);
}

.badge.error {
  background: rgba(248, 81, 73, 0.15);
  color: var(--red);
  border: 1px solid rgba(248, 81, 73, 0.3);
}

.badge.committed {
  background: rgba(210, 153, 34, 0.15);
  color: var(--amber);
  border: 1px solid rgba(210, 153, 34, 0.3);
}

.badge.reversible {
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border);
}

.badge.committed-lock {
  background: rgba(210, 153, 34, 0.1);
  color: var(--amber);
  border: 1px solid rgba(210, 153, 34, 0.2);
}
</style>
