<!--
  One catalog card (Shared = GLOBAL + TEAM, or Personal): server-paged, sorted, searched and filtered. Never asks
  for more than one page per request (T-S6-10 acceptance).
-->
<template>
  <q-table
    v-model:pagination="pagination"
    flat
    bordered
    :title="title"
    :rows="rows"
    :columns="columns"
    row-key="id"
    :loading="loading"
    :rows-per-page-options="[25, 50, 100]"
    binary-state-sort
    no-data-label="No items."
    @request="onRequest"
  >
    <template #top-right>
      <div class="row q-gutter-sm items-center">
        <q-select
          v-model="protocol"
          :options="protocolOptions"
          dense
          outlined
          emit-value
          map-options
          clearable
          label="Protocol"
          style="min-width: 130px"
        />
        <q-select v-model="site" :options="sites" dense outlined clearable label="Site" style="min-width: 110px" />
        <q-input v-model="q" dense outlined clearable debounce="300" placeholder="Search">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
      </div>
    </template>
    <template #body-cell-title="cell">
      <q-td :props="cell">
        <span :class="{ 'text-grey-6': !cell.row.reachable }">{{ cell.row.title }}</span>
        <q-tooltip v-if="!cell.row.reachable && cell.row.unreachable_reason">
          {{ cell.row.unreachable_reason }}
        </q-tooltip>
      </q-td>
    </template>
    <template #body-cell-scope="cell">
      <q-td :props="cell">
        <q-badge :color="scopeColor[cell.row.scope as Scope]" :label="cell.row.scope" />
      </q-td>
    </template>
    <template #body-cell-tags="cell">
      <q-td :props="cell">
        <q-chip v-for="t in cell.row.tags" :key="t" dense size="sm">{{ t }}</q-chip>
      </q-td>
    </template>
    <template #body-cell-actions="cell">
      <q-td :props="cell" class="text-right">
        <template v-if="cell.row.can_edit">
          <q-btn flat round dense icon="edit" :aria-label="`Edit ${cell.row.title}`" @click="emit('edit', cell.row)" />
          <q-btn
            flat
            round
            dense
            icon="delete"
            color="negative"
            :aria-label="`Delete ${cell.row.title}`"
            @click="emit('delete', cell.row)"
          />
        </template>
      </q-td>
    </template>
  </q-table>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import type { CodeNamed } from '@/api/admin';
import { useQuasar, type QTableColumn, type QTableProps } from 'quasar';
import { listCatalog, PROTOCOLS, type CatalogGroup, type ItemView, type Scope } from '@/api/catalog';

const props = defineProps<{ group: CatalogGroup; title: string; sites: string[]; teams: CodeNamed[] }>();
const emit = defineEmits<{ edit: [row: ItemView]; delete: [row: ItemView] }>();

const $q = useQuasar();

const teamCodes = (ids: string[]) => {
  const byId = new Map(props.teams.map((t) => [t.id, t.code]));
  return ids.length ? ids.map((id) => byId.get(id) ?? '?').join(', ') : '—';
};

const protocolOptions = PROTOCOLS.map((p) => ({ label: p === 'LOCAL_APP' ? 'Local app' : p, value: p }));
const scopeColor: Record<Scope, string> = { GLOBAL: 'primary', TEAM: 'teal', PERSONAL: 'grey-7' };

const columns = computed<QTableColumn<ItemView>[]>(() => [
  { name: 'title', label: 'Title', field: 'title', sortable: true, align: 'left' },
  { name: 'protocol', label: 'Protocol', field: 'protocol', sortable: true, align: 'left' },
  { name: 'target', label: 'Target', field: 'target', align: 'left' },
  { name: 'site', label: 'Site', field: 'site', sortable: true, align: 'left' },
  { name: 'scope', label: 'Scope', field: 'scope', align: 'left' },
  ...(props.group === 'shared'
    ? [{ name: 'teams', label: 'Teams', field: 'team_ids' as const, align: 'left' as const, format: teamCodes }]
    : []),
  { name: 'zones', label: 'Zones', field: (r) => r.zone_names.join(', '), align: 'left' },
  { name: 'tags', label: 'Tags', field: 'tags', align: 'left' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

const rows = ref<ItemView[]>([]);
const loading = ref(false);
const q = ref('');
const protocol = ref<string | null>(null);
const site = ref<string | null>(null);
const pagination = ref({ sortBy: 'title', descending: false, page: 1, rowsPerPage: 25, rowsNumber: 0 });

async function onRequest(req: Parameters<NonNullable<QTableProps['onRequest']>>[0]) {
  const { page, rowsPerPage, sortBy } = req.pagination;
  const descending = false; // the server sorts title | protocol | site ascending only (API.md §4.5)
  loading.value = true;
  try {
    const sort = sortBy ?? 'title';
    const res = await listCatalog({
      group: props.group,
      q: q.value ?? '',
      protocol: protocol.value ?? '',
      site: site.value ?? '',
      sort,
      page,
      page_size: rowsPerPage,
    });
    rows.value = res.results;
    pagination.value = { page, rowsPerPage, sortBy: sortBy ?? 'title', descending, rowsNumber: res.total };
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
  } finally {
    loading.value = false;
  }
}

function reload(resetPage = false) {
  void onRequest({
    pagination: { ...pagination.value, page: resetPage ? 1 : pagination.value.page },
    filter: undefined,
    getCellValue: () => undefined,
  });
}

watch([q, protocol, site], () => reload(true));
onMounted(() => reload());

defineExpose({ reload });
</script>
