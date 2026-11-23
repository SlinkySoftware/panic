<!-- /catalog: Shared (GLOBAL + TEAM) and Personal cards, plus the item modal. -->
<template>
  <q-page class="q-pa-lg q-gutter-y-lg">
    <div class="row items-center">
      <div class="text-h5 col">Catalog</div>
      <q-btn color="primary" icon="add" label="Add item" :disable="sites.length === 0" @click="openEdit(null)">
        <q-tooltip v-if="sites.length === 0">Create a site first</q-tooltip>
      </q-btn>
    </div>
    <CatalogTable
      ref="sharedTable"
      group="shared"
      title="Global & Team"
      :teams="teams"
      :zones="zones"
      :sites="sites"
      @edit="openEdit"
      @delete="confirmDelete"
    />
    <CatalogTable
      ref="personalTable"
      group="personal"
      title="Personal"
      :teams="teams"
      :zones="zones"
      :sites="sites"
      @edit="openEdit"
      @delete="confirmDelete"
    />
    <CatalogItemDialog
      v-model="editing"
      :item-id="editId"
      :sites="sites"
      :teams="teams"
      :zones="zones"
      @saved="reloadAll"
    />
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import CatalogTable from '@/components/catalog/CatalogTable.vue';
import CatalogItemDialog from '@/components/catalog/CatalogItemDialog.vue';
import { listCodeNamed, type CodeNamed } from '@/api/admin';
import { deleteCatalogItem, listZones, type ItemView, type Zone } from '@/api/catalog';

const $q = useQuasar();

const sites = ref<string[]>([]);
const teams = ref<CodeNamed[]>([]);
const zones = ref<Zone[]>([]);
const editing = ref(false);
const editId = ref<string | null>(null);
const sharedTable = ref<InstanceType<typeof CatalogTable> | null>(null);
const personalTable = ref<InstanceType<typeof CatalogTable> | null>(null);

function reloadAll() {
  sharedTable.value?.reload();
  personalTable.value?.reload();
}

function openEdit(row: ItemView | null) {
  editId.value = row?.id ?? null;
  editing.value = true;
}

function confirmDelete(row: ItemView) {
  $q.dialog({
    title: 'Delete item',
    message: `Delete "${row.title}"? It is also removed from every list that contains it.`,
    cancel: true,
    ok: { label: 'Delete', color: 'negative' },
  }).onOk(() => {
    void deleteCatalogItem(row.id)
      .then(() => {
        $q.notify({ type: 'positive', message: `Deleted ${row.title}` });
        reloadAll();
      })
      .catch((e: unknown) => $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) }));
  });
}

onMounted(async () => {
  const [s, t, z] = await Promise.allSettled([listCodeNamed('sites'), listCodeNamed('teams'), listZones()]);
  if (s.status === 'fulfilled') sites.value = s.value.map((x) => x.code).sort();
  if (t.status === 'fulfilled') teams.value = t.value;
  if (z.status === 'fulfilled') zones.value = z.value;
});
</script>
