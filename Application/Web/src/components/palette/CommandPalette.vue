<!--
  Command palette (T-S6-09): Ctrl+K / Cmd+K, or `/` outside a text field. Debounced `/ui/search`; arrows move,
  Enter launches an item (from its `launch`, no extra round trip) or opens a dashboard / list.
-->
<template>
  <q-dialog v-model="open" position="top" @hide="reset">
    <q-card style="width: 640px; max-width: 95vw; margin-top: 10vh">
      <q-input
        ref="inputEl"
        v-model="q"
        borderless
        autofocus
        class="q-px-md"
        placeholder="Search items, lists and dashboards…"
        data-testid="palette-input"
        @keydown="onKey"
      >
        <template #prepend><q-icon name="search" /></template>
        <template #append><q-spinner v-if="loading" size="sm" /></template>
      </q-input>
      <q-separator />
      <q-list v-if="results.length" dense style="max-height: 50vh; overflow-y: auto">
        <q-item
          v-for="(r, i) in results"
          :key="`${r.type}-${r.id}`"
          clickable
          :active="i === cursor"
          active-class="bg-blue-1 text-primary"
          @click="choose(r)"
          @mousemove="cursor = i"
        >
          <q-item-section avatar><q-icon :name="typeIcon[r.type]" /></q-item-section>
          <q-item-section>
            <q-item-label>{{ r.title }}</q-item-label>
            <q-item-label caption>{{ r.subtitle }}</q-item-label>
          </q-item-section>
          <q-item-section side class="text-caption">
            <q-badge v-if="r.item && !r.item.reachable" outline color="negative" label="Unavailable" />
            <span v-else>{{ r.type.toLowerCase() }}</span>
          </q-item-section>
        </q-item>
      </q-list>
      <div v-else-if="q.trim().length >= 2 && !loading" class="q-pa-md text-grey-6">No matches.</div>
      <div v-else class="q-pa-md text-grey-6 text-caption">
        Type at least 2 characters · ↑↓ to move · Enter to launch
      </div>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { requestJson } from '@/api/http';
import type { ItemView } from '@/api/catalog';
import { useLaunch } from '@/composables/useLaunch';
import { isPaletteShortcut } from './shortcut';

interface SearchResult {
  type: 'DASHBOARD' | 'ITEM' | 'LIST';
  id: string;
  title: string;
  subtitle: string;
  item?: ItemView;
}

const router = useRouter();
const { launch } = useLaunch();
const typeIcon = { DASHBOARD: 'dashboard', ITEM: 'dns', LIST: 'list' } as const;

const open = ref(false);
const q = ref('');
const results = ref<SearchResult[]>([]);
const cursor = ref(0);
const loading = ref(false);

let timer: ReturnType<typeof setTimeout> | undefined;
let seq = 0;
watch(q, (val) => {
  clearTimeout(timer);
  const term = val.trim();
  if (term.length < 2) {
    results.value = [];
    return;
  }
  timer = setTimeout(() => {
    const mine = ++seq;
    loading.value = true;
    requestJson<{ results: SearchResult[] }>('GET', `/ui/search?q=${encodeURIComponent(term)}&limit=20`)
      .then((res) => {
        if (mine !== seq) return; // a newer query superseded this one
        results.value = res.results;
        cursor.value = 0;
      })
      .catch(() => {
        if (mine === seq) results.value = [];
      })
      .finally(() => {
        if (mine === seq) loading.value = false;
      });
  }, 200);
});

function choose(r: SearchResult) {
  open.value = false;
  if (r.type === 'ITEM' && r.item) void launch(r.item);
  else if (r.type === 'DASHBOARD') void router.push({ name: 'dashboard-view', params: { id: r.id } });
  else if (r.type === 'LIST') void router.push({ name: 'lists', query: { open: r.id } });
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    const n = results.value.length;
    if (n) cursor.value = (cursor.value + (e.key === 'ArrowDown' ? 1 : n - 1)) % n;
  } else if (e.key === 'Enter') {
    e.preventDefault();
    const r = results.value[cursor.value];
    if (r) choose(r);
  }
}

function reset() {
  q.value = '';
  results.value = [];
  cursor.value = 0;
}

function onGlobalKey(e: KeyboardEvent) {
  if (!open.value && isPaletteShortcut(e)) {
    e.preventDefault();
    open.value = true;
  }
}

onMounted(() => window.addEventListener('keydown', onGlobalKey));
onBeforeUnmount(() => window.removeEventListener('keydown', onGlobalKey));

defineExpose({ show: () => (open.value = true) });
</script>
