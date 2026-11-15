<!-- /audit (T-S6-11): filters live in the URL query; keyset "Load more" (newest first). -->
<template>
  <q-page class="q-pa-lg">
    <div class="text-h5 q-mb-md">Audit</div>
    <q-form class="row q-col-gutter-sm q-mb-md" @submit="apply">
      <q-input v-model="f.q" class="col-12 col-md-3" label="Search summary" clearable v-bind="field" />
      <q-input v-model="f.actor" class="col-6 col-md-2" label="Actor" clearable v-bind="field" />
      <q-input
        v-model="f.action"
        class="col-6 col-md-2"
        label="Action"
        placeholder="admin.user.update"
        clearable
        v-bind="field"
      />
      <q-input v-model="f.target_type" class="col-6 col-md-2" label="Target type" clearable v-bind="field" />
      <q-input
        v-model="f.since"
        class="col-6 col-md-auto"
        label="Since"
        type="date"
        stack-label
        clearable
        v-bind="field"
      />
      <q-input
        v-model="f.until"
        class="col-6 col-md-auto"
        label="Until"
        type="date"
        stack-label
        clearable
        v-bind="field"
      />
      <div class="col-auto"><q-btn type="submit" color="primary" icon="filter_list" label="Apply" /></div>
    </q-form>

    <q-table
      flat
      bordered
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      hide-pagination
      :pagination="{ rowsPerPage: 0 }"
    >
      <template #body-cell-summary="cell">
        <q-td :props="cell" style="white-space: normal">
          {{ cell.row.summary }}
          <q-tooltip v-if="cell.row.details" max-width="480px">
            <pre class="q-ma-none" style="white-space: pre-wrap">{{ JSON.stringify(cell.row.details, null, 2) }}</pre>
          </q-tooltip>
        </q-td>
      </template>
    </q-table>
    <div class="q-mt-md text-center">
      <q-btn v-if="nextCursor" outline color="primary" label="Load more" :loading="loading" @click="fetchPage(false)" />
      <span v-else-if="rows.length" class="text-grey-6 text-caption">End of log.</span>
    </div>
  </q-page>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar, type QTableColumn } from 'quasar';
import { listAudit, type AuditEntry, type AuditFilters } from '@/api/settings';

const $q = useQuasar();
const route = useRoute();
const router = useRouter();
const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const KEYS = ['q', 'actor', 'action', 'target_type', 'since', 'until'] as const;

const columns: QTableColumn<AuditEntry>[] = [
  {
    name: 'created_at',
    label: 'When',
    field: 'created_at',
    align: 'left',
    format: (v: string) => new Date(v).toLocaleString(),
  },
  {
    name: 'actor',
    label: 'Actor',
    field: (r) => (r.view_as_username ? `${r.actor_username} (as ${r.view_as_username})` : r.actor_username),
    align: 'left',
  },
  { name: 'action', label: 'Action', field: 'action', align: 'left' },
  { name: 'target', label: 'Target', field: (r) => `${r.target_type} ${r.target_id}`, align: 'left' },
  { name: 'summary', label: 'Summary', field: 'summary', align: 'left' },
  { name: 'client_ip', label: 'Client IP', field: 'client_ip', align: 'left' },
];

const f = reactive<Record<(typeof KEYS)[number], string>>({
  q: '',
  actor: '',
  action: '',
  target_type: '',
  since: '',
  until: '',
});
const rows = ref<AuditEntry[]>([]);
const nextCursor = ref<string | null>(null);
const loading = ref(false);

function filtersFromRoute(): AuditFilters {
  const out: AuditFilters = {};
  for (const k of KEYS) {
    const v = route.query[k];
    if (typeof v === 'string' && v) out[k] = v;
  }
  return out;
}

async function fetchPage(reset: boolean) {
  loading.value = true;
  try {
    const filters = filtersFromRoute();
    // Date inputs give YYYY-MM-DD; make `until` inclusive of that whole day.
    if (filters.until && filters.until.length === 10) filters.until = `${filters.until}T23:59:59.999`;
    const res = await listAudit(filters, reset ? null : nextCursor.value);
    rows.value = reset ? res.results : [...rows.value, ...res.results];
    nextCursor.value = res.next_cursor;
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
  } finally {
    loading.value = false;
  }
}

function apply() {
  const query: Record<string, string> = {};
  for (const k of KEYS) if (f[k]) query[k] = f[k];
  void router.replace({ query });
}

watch(
  () => route.query,
  () => {
    for (const k of KEYS) f[k] = typeof route.query[k] === 'string' ? route.query[k] : '';
    void fetchPage(true);
  },
  { immediate: true },
);
</script>
