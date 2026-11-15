<!-- A read-only command line with a copy button (works over plain HTTP: Quasar's copyToClipboard fallback). -->
<template>
  <div class="row no-wrap items-start q-gutter-x-sm">
    <pre class="col mono q-ma-none q-pa-sm rounded-borders panic-command">{{ command }}</pre>
    <q-btn flat round dense icon="content_copy" aria-label="Copy" @click="copy">
      <q-tooltip>Copy</q-tooltip>
    </q-btn>
  </div>
</template>

<script setup lang="ts">
import { copyToClipboard, useQuasar } from 'quasar';

const props = defineProps<{ command: string }>();
const $q = useQuasar();

async function copy() {
  try {
    await copyToClipboard(props.command);
    $q.notify({ type: 'positive', message: 'Copied', timeout: 1500 });
  } catch {
    $q.notify({ type: 'negative', message: 'Could not copy; select the text instead' });
  }
}
</script>

<style scoped>
.panic-command {
  white-space: pre-wrap;
  word-break: break-all;
  background: var(--surface-sunken);
  border: 1px solid var(--border);
  max-height: 160px;
  overflow-y: auto;
}
</style>
