<!-- Add Widget: a HOST (one catalog item) or a LIST, picked with a server-searched picker over visible ones. -->
<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 520px; max-width: 95vw">
      <q-card-section class="text-h6">Add widget</q-card-section>
      <q-card-section class="q-gutter-y-md">
        <q-btn-toggle
          v-model="type"
          spread
          no-caps
          toggle-color="primary"
          :options="[
            { label: 'Host (one item)', value: 'HOST', icon: 'dns' },
            { label: 'List', value: 'LIST', icon: 'list' },
          ]"
        />
        <q-input v-model="q" outlined dense clearable debounce="300" autofocus placeholder="Search">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <q-list bordered separator class="rounded-borders" style="max-height: 320px; overflow-y: auto">
          <q-item v-if="loading"
            ><q-item-section class="flex flex-center"><q-spinner /></q-item-section
          ></q-item>
          <q-item v-else-if="options.length === 0"
            ><q-item-section class="text-grey-6"
              >Nothing found (items and lists already on this dashboard are not shown).</q-item-section
            ></q-item
          >
          <q-item v-for="o in options" :key="o.id" clickable @click="pick(o)">
            <q-item-section>
              <q-item-label>{{ o.title }}</q-item-label>
              <q-item-label caption>{{ o.caption }}</q-item-label>
            </q-item-section>
            <q-item-section side><q-badge outline color="grey-7" :label="o.scope" /></q-item-section>
          </q-item>
        </q-list>
      </q-card-section>
      <q-card-actions align="right"><q-btn v-close-popup flat label="Cancel" /></q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { listCatalog, protocolsLabel } from '@/api/catalog';
import { listLists } from '@/api/lists';

export interface Picked {
  type: 'HOST' | 'LIST';
  id: string;
  title: string;
}

// `exclude`: catalog item and list ids already on the dashboard; they are not offered again.
const props = defineProps<{ modelValue: boolean; exclude: Set<string> }>();
const emit = defineEmits<{ 'update:modelValue': [open: boolean]; pick: [picked: Picked] }>();

interface Option {
  id: string;
  title: string;
  caption: string;
  scope: string;
}

const type = ref<'HOST' | 'LIST'>('HOST');
const q = ref('');
const options = ref<Option[]>([]);
const loading = ref(false);

async function search() {
  loading.value = true;
  try {
    // Both cards (shared + personal): everything visible to the editor; the server re-checks on save.
    if (type.value === 'HOST') {
      const pages = await Promise.all(
        (['shared', 'personal'] as const).map((group) =>
          listCatalog({ group, q: q.value ?? '', page: 1, page_size: 25 }),
        ),
      );
      options.value = pages.flatMap((p) =>
        p.results
          .filter((i) => !props.exclude.has(i.id))
          .map((i) => ({
            id: i.id,
            title: i.title,
            caption: `${protocolsLabel(i.protocols)} · ${i.target}`,
            scope: i.scope,
          })),
      );
    } else {
      const pages = await Promise.all(
        (['shared', 'personal'] as const).map((group) =>
          listLists({ group, q: q.value ?? '', page: 1, page_size: 25 }),
        ),
      );
      options.value = pages.flatMap((p) =>
        p.results
          .filter((l) => !props.exclude.has(l.id))
          .map((l) => ({ id: l.id, title: l.title, caption: `${l.item_count} items`, scope: l.scope })),
      );
    }
  } catch {
    options.value = [];
  } finally {
    loading.value = false;
  }
}

function pick(o: Option) {
  emit('pick', { type: type.value, id: o.id, title: o.title });
  emit('update:modelValue', false);
}

watch([type, q], search);
watch(
  () => props.modelValue,
  (open) => {
    if (!open) return;
    q.value = '';
    void search();
  },
);
</script>
