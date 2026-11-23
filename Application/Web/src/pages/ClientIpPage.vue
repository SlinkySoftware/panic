<!-- /settings/client-ip: how the server derived this request's client IP and zone (API.md §6). -->
<template>
  <q-page class="q-pa-lg q-gutter-y-lg">
    <div class="row items-center">
      <div class="text-h5 col">Client-IP diagnostics</div>
      <q-btn flat icon="refresh" label="Refresh" :loading="loading" @click="load" />
    </div>
    <q-banner v-if="error" class="bg-negative text-white" rounded>{{ error }}</q-banner>
    <template v-if="d">
      <q-card flat bordered>
        <q-card-section class="row q-col-gutter-md">
          <div v-for="s in summary" :key="s.label" class="col-6 col-md-3">
            <div class="text-caption text-grey-7">{{ s.label }}</div>
            <div class="text-body1" style="font-family: monospace">{{ s.value }}</div>
          </div>
        </q-card-section>
      </q-card>

      <q-table
        flat
        bordered
        title="Hops (client → server)"
        :rows="d.hops"
        :columns="hopColumns"
        row-key="index"
        hide-pagination
        :pagination="{ rowsPerPage: 0 }"
        no-data-label="No forwarded hops: the peer is the client."
      >
        <template #body-cell="cell">
          <q-td :props="cell" style="font-family: monospace">{{ fmt(cell.value) }}</q-td>
        </template>
      </q-table>

      <div class="row q-col-gutter-lg">
        <div class="col-12 col-md-6">
          <q-card flat bordered>
            <q-card-section class="text-subtitle2">Trust policy</q-card-section>
            <q-markup-table flat dense>
              <tbody>
                <tr v-for="(v, k) in d.policy" :key="k">
                  <td class="text-grey-7">{{ k }}</td>
                  <td style="font-family: monospace">{{ fmt(v) }}</td>
                </tr>
              </tbody>
            </q-markup-table>
          </q-card>
        </div>
        <div class="col-12 col-md-6">
          <q-card flat bordered>
            <q-card-section class="text-subtitle2">Raw headers</q-card-section>
            <q-markup-table flat dense>
              <tbody>
                <tr v-for="(v, k) in d.raw" :key="k">
                  <td class="text-grey-7">{{ k }}</td>
                  <td style="font-family: monospace; word-break: break-all">{{ v ?? '—' }}</td>
                </tr>
              </tbody>
            </q-markup-table>
          </q-card>
        </div>
      </div>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import type { QTableColumn } from 'quasar';
import { getClientIp, type ClientIpDiagnostics } from '@/api/settings';

const d = ref<ClientIpDiagnostics | null>(null);
const loading = ref(false);
const error = ref('');

const fmt = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'string' ? v : JSON.stringify(v));

const summary = computed(() => {
  const x = d.value;
  if (!x) return [];
  return [
    { label: 'Client IP', value: x.client_ip ?? '—' },
    { label: 'Decision', value: x.decision },
    { label: 'Zone', value: x.zone ? `${x.zone.name}${x.zone.matched_cidr ? ` (${x.zone.matched_cidr})` : ''}` : '—' },
    { label: 'Zone source', value: x.zone_source },
    { label: 'Peer (REMOTE_ADDR)', value: x.remote_addr },
    { label: 'Peer trusted', value: x.peer_trusted ? 'yes' : 'no' },
    { label: 'Ignored left hops', value: String(x.ignored_left_hops) },
    { label: 'Truncated', value: x.truncated ? 'yes' : 'no' },
  ];
});

// Hop objects come straight from the server model: show whatever fields it has.
const hopColumns = computed<QTableColumn<Record<string, unknown>>[]>(() =>
  Object.keys(d.value?.hops[0] ?? {}).map((k) => ({ name: k, label: k.replace(/_/g, ' '), field: k, align: 'left' })),
);

async function load() {
  loading.value = true;
  error.value = '';
  try {
    d.value = await getClientIp();
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>
