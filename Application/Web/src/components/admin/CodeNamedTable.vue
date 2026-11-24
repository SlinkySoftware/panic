<!--
  Sites and Teams admin table: search, create, edit, copy (a new one prefilled from a row, saveable once changed),
  delete. Everyone can read; only a Global Admin sees the
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
          <q-btn
            v-if="kind === 'teams'"
            flat
            round
            dense
            icon="group"
            :aria-label="`Members of ${cell.row.code}`"
            @click="openMembers(cell.row)"
          />
          <q-btn flat round dense icon="edit" :aria-label="`Edit ${cell.row.code}`" @click="openEdit(cell.row)" />
          <q-btn
            flat
            round
            dense
            icon="content_copy"
            :aria-label="`Copy ${cell.row.code}`"
            @click="openEdit(cell.row, true)"
          >
            <q-tooltip>Copy to a new {{ noun }}</q-tooltip>
          </q-btn>
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
      <q-card style="width: 560px; max-width: 95vw">
        <q-form data-testid="code-named-form" @submit="save">
          <q-card-section class="text-h6">{{ heading }}</q-card-section>
          <q-card-section class="panic-form-row">
            <div class="panic-form-fields q-gutter-sm">
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
            </div>
            <div class="panic-form-actions">
              <q-btn type="submit" color="primary" label="Save" :loading="saving" :disable="unchangedCopy">
                <q-tooltip v-if="unchangedCopy">Change something before saving the copy</q-tooltip>
              </q-btn>
              <q-btn v-close-popup flat label="Cancel" />
            </div>
          </q-card-section>
        </q-form>
      </q-card>
    </q-dialog>

    <q-dialog v-model="membersOpen">
      <q-card style="width: 480px; max-width: 95vw">
        <q-card-section class="text-h6">{{ membersOf?.code }} members</q-card-section>
        <q-card-section class="q-pt-none text-caption text-grey-7">
          Read-only. Change membership on each user's page.
        </q-card-section>
        <q-list bordered separator style="max-height: 50vh; overflow-y: auto">
          <q-item v-if="membersLoading"
            ><q-item-section class="flex flex-center"><q-spinner /></q-item-section
          ></q-item>
          <q-item v-else-if="members.length === 0"
            ><q-item-section class="text-grey-6">No members.</q-item-section></q-item
          >
          <q-item
            v-for="m in members"
            :key="m.id"
            clickable
            :to="{ name: 'settings-user-detail', params: { id: m.id } }"
            @click="membersOpen = false"
          >
            <q-item-section>
              <q-item-label>{{ m.display_name }}</q-item-label>
              <q-item-label caption>{{ m.username }}</q-item-label>
            </q-item-section>
            <q-item-section v-if="m.disabled" side><q-badge color="grey-6" label="Disabled" /></q-item-section>
          </q-item>
        </q-list>
        <q-card-section v-if="membersTotal > members.length" class="text-caption text-grey-7">
          Showing {{ members.length }} of {{ membersTotal }}.
        </q-card-section>
        <q-card-actions align="right"><q-btn v-close-popup flat label="Close" /></q-card-actions>
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
import { listTeamMembers, type UserSummary } from '@/api/users';
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
// Set while copying a row: the fields as first loaded, so Save waits for a change.
const copySnapshot = ref('');
const fields = () => JSON.stringify([form.code, form.name, form.description]);
const unchangedCopy = computed(() => !!copySnapshot.value && fields() === copySnapshot.value);
const heading = computed(() =>
  copySnapshot.value ? `Copy ${props.noun}` : form.id ? `Edit ${props.noun}` : `Add ${props.noun}`,
);

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

function openEdit(row: CodeNamed | null, copy = false) {
  Object.assign(form, row ?? { id: '', code: '', name: '', description: '' });
  if (copy) form.id = '';
  copySnapshot.value = copy ? fields() : '';
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

const membersOpen = ref(false);
const membersOf = ref<CodeNamed | null>(null);
const members = ref<UserSummary[]>([]);
const membersTotal = ref(0);
const membersLoading = ref(false);
async function openMembers(team: CodeNamed) {
  membersOf.value = team;
  members.value = [];
  membersOpen.value = true;
  membersLoading.value = true;
  try {
    const page = await listTeamMembers(team.id);
    members.value = page.results;
    membersTotal.value = page.total;
  } catch (e) {
    notifyError(e);
  } finally {
    membersLoading.value = false;
  }
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
