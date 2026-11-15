<!--
  Sites and Teams admin table: search, create, edit, delete. Everyone can read; only a Global Admin sees the
  write actions (the server enforces this regardless).
-->
<template>
  <q-page class="q-pa-lg">
    <q-table
      flat
      bordered
      :title="title"
      :rows="rows"
      :columns="columns"
      row-key="id"
      :filter="filter"
      :loading="loading"
      :pagination="{ rowsPerPage: 25, sortBy: 'code' }"
      :no-data-label="`No ${noun}s yet.`"
    >
      <template #top-right>
        <q-input v-model="filter" dense outlined clearable debounce="200" placeholder="Search" class="q-mr-sm">
          <template #prepend><q-icon name="search" /></template>
        </q-input>
        <q-btn v-if="session.isAdmin" color="primary" icon="add" :label="`Add ${noun}`" @click="openEdit(null)" />
      </template>
      <template #body-cell-actions="cell">
        <q-td :props="cell" class="text-right">
          <q-btn flat round dense icon="edit" :aria-label="`Edit ${cell.row.code}`" @click="openEdit(cell.row)" />
          <q-btn
            flat
            round
            dense
            icon="delete"
            color="negative"
            :aria-label="`Delete ${cell.row.code}`"
            @click="confirmDelete(cell.row)"
          />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="editing" persistent>
      <q-card style="min-width: 420px">
        <q-form data-testid="code-named-form" @submit="save">
          <q-card-section class="text-h6">{{ form.id ? `Edit ${noun}` : `Add ${noun}` }}</q-card-section>
          <q-card-section class="q-gutter-sm">
            <q-input
              v-model="form.code"
              label="Code"
              outlined
              dense
              autofocus
              :rules="[required]"
              :error="!!fieldErrors.code"
              :error-message="fieldErrors.code"
              @update:model-value="form.code = String($event ?? '').toUpperCase()"
            />
            <q-input
              v-model="form.name"
              label="Name"
              outlined
              dense
              :rules="[required]"
              :error="!!fieldErrors.name"
              :error-message="fieldErrors.name"
            />
            <q-input v-model="form.description" label="Description" outlined dense type="textarea" autogrow />
            <q-banner v-if="saveError" class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat label="Cancel" />
            <q-btn type="submit" color="primary" label="Save" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import {
  createCodeNamed,
  deleteCodeNamed,
  listCodeNamed,
  updateCodeNamed,
  type CodeNamed,
  type CodeNamedKind,
} from '@/api/admin';
import { ApiError } from '@/api/http';
import { useSessionStore } from '@/stores/session';

const props = defineProps<{ kind: CodeNamedKind; title: string; noun: string }>();

const $q = useQuasar();
const session = useSessionStore();

const rows = ref<CodeNamed[]>([]);
const loading = ref(false);
const filter = ref('');

const columns = computed<QTableColumn<CodeNamed>[]>(() => [
  { name: 'code', label: 'Code', field: 'code', sortable: true, align: 'left' },
  { name: 'name', label: 'Name', field: 'name', sortable: true, align: 'left' },
  { name: 'description', label: 'Description', field: 'description', align: 'left' },
  ...(session.isAdmin ? [{ name: 'actions', label: '', field: 'id' as const, align: 'right' as const }] : []),
]);

const editing = ref(false);
const saving = ref(false);
const saveError = ref('');
const fieldErrors = ref<Record<string, string>>({});
const form = reactive({ id: '', code: '', name: '', description: '' });

const required = (v: string) => (!!v && v.trim().length > 0) || 'Required';

function notifyError(e: unknown) {
  $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
}

async function load() {
  loading.value = true;
  try {
    rows.value = await listCodeNamed(props.kind);
  } catch (e) {
    notifyError(e);
  } finally {
    loading.value = false;
  }
}

function openEdit(row: CodeNamed | null) {
  Object.assign(form, row ?? { id: '', code: '', name: '', description: '' });
  saveError.value = '';
  fieldErrors.value = {};
  editing.value = true;
}

async function save() {
  saving.value = true;
  saveError.value = '';
  fieldErrors.value = {};
  const body = { code: form.code.trim(), name: form.name.trim(), description: form.description.trim() };
  try {
    if (form.id) await updateCodeNamed(props.kind, form.id, body);
    else await createCodeNamed(props.kind, body);
    editing.value = false;
    $q.notify({ type: 'positive', message: `Saved ${props.noun} ${body.code}` });
    await load();
  } catch (e) {
    if (e instanceof ApiError) {
      fieldErrors.value = Object.fromEntries(Object.entries(e.fieldErrors).map(([k, v]) => [k, v.join(' ')]));
    }
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

function confirmDelete(row: CodeNamed) {
  $q.dialog({
    title: `Delete ${props.noun}`,
    message: `Delete ${row.code} (${row.name})?`,
    cancel: true,
    ok: { label: 'Delete', color: 'negative' },
  }).onOk(() => {
    void (async () => {
      try {
        await deleteCodeNamed(props.kind, row.id);
        $q.notify({ type: 'positive', message: `Deleted ${props.noun} ${row.code}` });
        await load();
      } catch (e) {
        notifyError(e);
      }
    })();
  });
}

// Sites and Teams share this component, so the router reuses one instance across them: reload on every kind change.
watch(
  () => props.kind,
  () => {
    rows.value = [];
    filter.value = '';
    editing.value = false;
    void load();
  },
  { immediate: true },
);
</script>
