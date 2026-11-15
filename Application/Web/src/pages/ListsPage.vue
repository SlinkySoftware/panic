<!-- /lists (T-S6-10): Shared and Personal cards; `?open=<id>` opens a list (the LIST widget's "Show all"). -->
<template>
  <q-page class="q-pa-lg q-gutter-y-lg">
    <div class="row items-center">
      <div class="text-h5 col">Lists</div>
      <q-btn color="primary" icon="add" label="New list" @click="open(null)" />
    </div>
    <ListsTable
      ref="sharedTable"
      group="shared"
      title="Global & Team"
      :teams="teams"
      @open="open($event.id)"
      @delete="confirmDelete"
    />
    <ListsTable
      ref="personalTable"
      group="personal"
      title="Personal"
      :teams="teams"
      @open="open($event.id)"
      @delete="confirmDelete"
    />
    <EditListDialog v-model="editing" :list-id="editId" :teams="teams" @saved="reloadAll" />
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import ListsTable from '@/components/lists/ListsTable.vue';
import EditListDialog from '@/components/lists/EditListDialog.vue';
import { listCodeNamed, type CodeNamed } from '@/api/admin';
import { deleteList, type ListSummary } from '@/api/lists';

const $q = useQuasar();
const route = useRoute();
const router = useRouter();

const teams = ref<CodeNamed[]>([]);
const editing = ref(false);
const editId = ref<string | null>(null);
const sharedTable = ref<InstanceType<typeof ListsTable> | null>(null);
const personalTable = ref<InstanceType<typeof ListsTable> | null>(null);

function reloadAll() {
  sharedTable.value?.reload();
  personalTable.value?.reload();
}

function open(id: string | null) {
  editId.value = id;
  editing.value = true;
}

// Drop ?open= once the dialog closes so a reload does not reopen it.
watch(editing, (v) => {
  if (!v && route.query.open) void router.replace({ query: { ...route.query, open: undefined } });
});

function confirmDelete(row: ListSummary) {
  $q.dialog({
    title: 'Delete list',
    message: `Delete "${row.title}"? Dashboard widgets showing it become placeholders.`,
    cancel: true,
    ok: { label: 'Delete', color: 'negative' },
  }).onOk(() => {
    void deleteList(row.id, row.version)
      .then(() => {
        $q.notify({ type: 'positive', message: `Deleted ${row.title}` });
        reloadAll();
      })
      .catch((e: unknown) => $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) }));
  });
}

onMounted(async () => {
  if (typeof route.query.open === 'string') open(route.query.open);
  try {
    teams.value = await listCodeNamed('teams');
  } catch {
    teams.value = [];
  }
});
</script>
