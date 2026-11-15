<!-- /settings/orphans (T-S6-11): resources left with no team / owner; assign to an enabled user, or delete. -->
<template>
  <q-page class="q-pa-lg">
    <q-table
      v-model:pagination="pagination"
      flat
      bordered
      title="Orphans"
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      no-data-label="No orphaned resources."
      @request="onRequest"
    >
      <template #top-right>
        <div class="row q-gutter-sm">
          <q-select
            v-model="kind"
            :options="kindOptions"
            label="Kind"
            emit-value
            map-options
            clearable
            style="min-width: 130px"
            v-bind="field"
          />
          <q-input v-model="q" placeholder="Search" debounce="300" clearable v-bind="field">
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </div>
      </template>
      <template #body-cell-actions="cell">
        <q-td :props="cell" class="text-right">
          <q-btn flat dense no-caps icon="person" label="Assign" color="primary" @click="openAssign(cell.row)" />
          <q-btn
            flat
            round
            dense
            icon="delete"
            color="negative"
            :aria-label="`Delete ${cell.row.title}`"
            @click="confirmDelete(cell.row)"
          />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="assigning">
      <q-card v-if="target" style="width: 440px; max-width: 95vw">
        <q-card-section class="text-h6">Assign "{{ target.title }}"</q-card-section>
        <q-card-section class="q-gutter-y-sm">
          <div class="text-caption text-grey-7">It becomes a PERSONAL {{ target.kind }} of the chosen user.</div>
          <q-select
            v-model="assignee"
            :options="userOptions"
            label="User"
            use-input
            input-debounce="300"
            emit-value
            map-options
            v-bind="field"
            @filter="searchUsers"
          />
          <q-banner v-if="assignError" class="bg-negative text-white" rounded dense>{{ assignError }}</q-banner>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat label="Cancel" />
          <q-btn color="primary" label="Assign" :disable="!assignee" @click="assign" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useQuasar, type QTableColumn, type QTableProps } from 'quasar';
import { assignOrphan, deleteOrphan, listOrphans, type Orphan } from '@/api/settings';
import { listUsers } from '@/api/users';

const $q = useQuasar();
const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const kindOptions = [
  { label: 'Catalog items', value: 'catalog' },
  { label: 'Lists', value: 'list' },
  { label: 'Dashboards', value: 'dashboard' },
];

const columns: QTableColumn<Orphan>[] = [
  { name: 'kind', label: 'Kind', field: 'kind', align: 'left' },
  { name: 'title', label: 'Title', field: 'title', align: 'left' },
  { name: 'scope', label: 'Was', field: 'scope', align: 'left' },
  {
    name: 'former',
    label: 'Former owners / teams',
    field: (r) => [...(r.former_owners ?? []), ...(r.former_team_ids ?? [])].join(', ') || '—',
    align: 'left',
  },
  {
    name: 'updated_at',
    label: 'Updated',
    field: 'updated_at',
    align: 'left',
    format: (v: string) => new Date(v).toLocaleString(),
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

const rows = ref<Orphan[]>([]);
const loading = ref(false);
const kind = ref<string | null>(null);
const q = ref('');
const pagination = ref({ sortBy: 'title', descending: false, page: 1, rowsPerPage: 25, rowsNumber: 0 });

async function onRequest(req: Parameters<NonNullable<QTableProps['onRequest']>>[0]) {
  const { page, rowsPerPage } = req.pagination;
  loading.value = true;
  try {
    const res = await listOrphans({ kind: kind.value ?? '', q: q.value ?? '', page, page_size: rowsPerPage });
    rows.value = res.results;
    pagination.value = { ...pagination.value, page, rowsPerPage, rowsNumber: res.total };
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
  } finally {
    loading.value = false;
  }
}
const reload = (resetPage = false) =>
  onRequest({
    pagination: { ...pagination.value, page: resetPage ? 1 : pagination.value.page },
    filter: undefined,
    getCellValue: () => undefined,
  });
watch([kind, q], () => void reload(true));
onMounted(() => void reload());

const assigning = ref(false);
const target = ref<Orphan | null>(null);
const assignee = ref<string | null>(null);
const assignError = ref('');
const userOptions = ref<{ label: string; value: string }[]>([]);
function openAssign(o: Orphan) {
  target.value = o;
  assignee.value = null;
  assignError.value = '';
  assigning.value = true;
}
function searchUsers(val: string, update: (fn: () => void) => void) {
  listUsers({ q: val, disabled: 'false', page: 1, page_size: 25 })
    .then((res) =>
      update(
        () =>
          (userOptions.value = res.results.map((u) => ({
            label: `${u.display_name} (${u.username})`,
            value: u.username,
          }))),
      ),
    )
    .catch(() => update(() => (userOptions.value = [])));
}
async function assign() {
  const o = target.value;
  if (!o || !assignee.value) return;
  try {
    const res = await assignOrphan(o.kind, o.id, assignee.value);
    const dropped = res.dropped_item_ids?.length ?? 0;
    $q.notify({
      type: 'positive',
      message: `Assigned to ${assignee.value}`,
      ...(dropped ? { caption: `${dropped} item(s) the user cannot see were dropped from the list` } : {}),
    });
    assigning.value = false;
    await reload();
  } catch (e) {
    assignError.value = e instanceof Error ? e.message : String(e);
  }
}

function confirmDelete(o: Orphan) {
  $q.dialog({
    title: 'Delete orphan',
    message: `Delete "${o.title}"?`,
    cancel: true,
    ok: { label: 'Delete', color: 'negative' },
  }).onOk(() => {
    void deleteOrphan(o.kind, o.id)
      .then(() => reload())
      .catch((e: unknown) => $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) }));
  });
}
</script>
