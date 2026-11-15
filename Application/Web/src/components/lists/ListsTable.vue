<!-- One lists card (Shared = GLOBAL + TEAM, or Personal): server-paged and searched. -->
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
    no-data-label="No lists."
    @request="onRequest"
    @row-click="(_evt, row) => emit('open', row)"
  >
    <template #top-right>
      <q-input v-model="q" dense outlined clearable debounce="300" placeholder="Search">
        <template #prepend><q-icon name="search" /></template>
      </q-input>
    </template>
    <template #body-cell-scope="cell">
      <q-td :props="cell"><q-badge :color="scopeColor[cell.row.scope as Scope]" :label="cell.row.scope" /></q-td>
    </template>
    <template #body-cell-actions="cell">
      <q-td :props="cell" class="text-right">
        <q-btn
          v-if="cell.row.can_edit"
          flat
          round
          dense
          icon="delete"
          color="negative"
          :aria-label="`Delete ${cell.row.title}`"
          @click.stop="emit('delete', cell.row)"
        />
      </q-td>
    </template>
  </q-table>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import type { CodeNamed } from '@/api/admin';
import { useQuasar, type QTableColumn, type QTableProps } from 'quasar';
import type { CatalogGroup, Scope } from '@/api/catalog';
import { listLists, type ListSummary } from '@/api/lists';

const props = defineProps<{ group: CatalogGroup; title: string; teams: CodeNamed[] }>();
const emit = defineEmits<{ open: [row: ListSummary]; delete: [row: ListSummary] }>();

const $q = useQuasar();

const teamCodes = (ids: string[]) => {
  const byId = new Map(props.teams.map((t) => [t.id, t.code]));
  return ids.length ? ids.map((id) => byId.get(id) ?? '?').join(', ') : '—';
};
const scopeColor: Record<Scope, string> = { GLOBAL: 'primary', TEAM: 'teal', PERSONAL: 'grey-7' };

const columns = computed<QTableColumn<ListSummary>[]>(() => [
  { name: 'title', label: 'Title', field: 'title', align: 'left' },
  { name: 'description', label: 'Description', field: 'description', align: 'left' },
  { name: 'scope', label: 'Scope', field: 'scope', align: 'left' },
  ...(props.group === 'shared'
    ? [{ name: 'teams', label: 'Teams', field: 'team_ids' as const, align: 'left' as const, format: teamCodes }]
    : []),
  { name: 'item_count', label: 'Items', field: 'item_count', align: 'right' },
  { name: 'actions', label: '', field: 'id', align: 'right' },
]);

const rows = ref<ListSummary[]>([]);
const loading = ref(false);
const q = ref('');
const pagination = ref({ sortBy: 'title', descending: false, page: 1, rowsPerPage: 25, rowsNumber: 0 });

async function onRequest(req: Parameters<NonNullable<QTableProps['onRequest']>>[0]) {
  const { page, rowsPerPage } = req.pagination;
  loading.value = true;
  try {
    const res = await listLists({ group: props.group, q: q.value ?? '', page, page_size: rowsPerPage });
    rows.value = res.results;
    pagination.value = { ...pagination.value, page, rowsPerPage, rowsNumber: res.total };
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

watch(q, () => reload(true));
onMounted(() => reload());

defineExpose({ reload });
</script>
