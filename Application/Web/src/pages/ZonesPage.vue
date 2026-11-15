<!--
  /zones (T-S6-11): zones with CIDR editing and Test IP. The built-in Default zone is shown as such; only its
  description can be edited (the server enforces this too). Non-admins see names only.
-->
<template>
  <q-page class="q-pa-lg q-gutter-y-lg">
    <q-table
      flat
      bordered
      title="Zones"
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :pagination="{ rowsPerPage: 0, sortBy: 'priority' }"
      hide-pagination
    >
      <template #top-right>
        <q-btn v-if="session.isAdmin" color="primary" icon="add" label="Add zone" @click="openEdit(null)" />
      </template>
      <template #body-cell-name="cell">
        <q-td :props="cell">
          {{ cell.row.name }}
          <q-badge v-if="cell.row.builtin" outline color="grey-7" label="built-in" class="q-ml-xs" />
        </q-td>
      </template>
      <template #body-cell-cidrs="cell">
        <q-td :props="cell">
          <q-chip v-for="c in cell.row.cidrs" :key="c" dense size="sm" style="font-family: monospace">{{ c }}</q-chip>
          <span v-if="cell.row.builtin" class="text-grey-6 text-caption">Any address no other zone matches</span>
        </q-td>
      </template>
      <template #body-cell-actions="cell">
        <q-td :props="cell" class="text-right">
          <q-btn flat round dense icon="edit" :aria-label="`Edit ${cell.row.name}`" @click="openEdit(cell.row)" />
          <q-btn
            v-if="!cell.row.builtin"
            flat
            round
            dense
            icon="delete"
            color="negative"
            :aria-label="`Delete ${cell.row.name}`"
            @click="confirmDelete(cell.row)"
          />
        </q-td>
      </template>
    </q-table>

    <q-card v-if="session.isAdmin" flat bordered>
      <q-card-section class="text-h6 q-pb-none">Test IP</q-card-section>
      <q-card-section>
        <q-form class="row q-col-gutter-md items-center" @submit="runTest">
          <q-input v-model="ip" class="col-12 col-sm-5" label="IP address" placeholder="192.0.2.10" v-bind="field" />
          <div class="col-auto"><q-btn type="submit" color="primary" label="Test" :loading="testing" /></div>
        </q-form>
        <div v-if="testResult" class="q-mt-md">
          <div>
            Resolves to <b>{{ testResult.resolution.winning_zone?.name ?? 'none' }}</b>
            <span class="text-grey-7">
              ({{
                testResult.resolution.zone_source === 'CIDR'
                  ? `matched ${testResult.resolution.matched_cidr}`
                  : 'no CIDR matched'
              }})
            </span>
          </div>
          <div class="text-grey-8">
            {{ testResult.reachable_count }} catalog items reachable, {{ testResult.blocked_count }} blocked from there.
          </div>
        </div>
        <q-banner v-if="testError" class="bg-negative text-white q-mt-md" rounded dense>{{ testError }}</q-banner>
      </q-card-section>
    </q-card>

    <q-dialog v-model="editing" persistent>
      <q-card style="width: 520px; max-width: 95vw">
        <q-form @submit="save">
          <q-card-section class="text-h6">{{ form.id ? `Edit ${form.name}` : 'Add zone' }}</q-card-section>
          <q-card-section class="row q-col-gutter-md">
            <q-input
              v-model="form.name"
              class="col-12 col-sm-8"
              label="Name"
              :disable="form.builtin"
              :rules="[required]"
              v-bind="{ ...field, ...err('name') }"
            />
            <q-input
              v-model.number="form.priority"
              class="col-12 col-sm-4"
              type="number"
              label="Priority"
              hint="Tie-breaker only: higher wins"
              :disable="form.builtin"
              v-bind="{ ...field, ...err('priority') }"
            />
            <q-select
              v-if="!form.builtin"
              v-model="form.cidrs"
              class="col-12"
              label="CIDRs"
              placeholder="Type a CIDR and press Enter"
              multiple
              use-chips
              use-input
              new-value-mode="add-unique"
              hide-dropdown-icon
              v-bind="{ ...field, ...err('cidrs') }"
            />
            <q-input
              v-model="form.description"
              class="col-12"
              label="Description"
              type="textarea"
              autogrow
              v-bind="field"
            />
            <div v-if="saveError" class="col-12">
              <q-banner class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
            </div>
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
import { computed, onMounted, reactive, ref } from 'vue';
import { useQuasar, type QTableColumn } from 'quasar';
import {
  createZone,
  deleteZone,
  listZonesAdmin,
  testIp,
  updateZone,
  type TestIpResult,
  type ZoneAdmin,
} from '@/api/admin';
import { ApiError } from '@/api/http';
import { useSessionStore } from '@/stores/session';

const $q = useQuasar();
const session = useSessionStore();

const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const required = (v: string) => (!!v && v.trim().length > 0) || 'Required';

const rows = ref<ZoneAdmin[]>([]);
const loading = ref(false);
const columns = computed<QTableColumn<ZoneAdmin>[]>(() => [
  { name: 'name', label: 'Name', field: 'name', align: 'left', sortable: true },
  ...(session.isAdmin
    ? [
        { name: 'priority', label: 'Priority', field: 'priority' as const, align: 'right' as const, sortable: true },
        { name: 'cidrs', label: 'CIDRs', field: 'cidrs' as const, align: 'left' as const },
        { name: 'description', label: 'Description', field: 'description' as const, align: 'left' as const },
        { name: 'actions', label: '', field: 'id' as const, align: 'right' as const },
      ]
    : []),
]);

async function load() {
  loading.value = true;
  try {
    rows.value = await listZonesAdmin();
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
  } finally {
    loading.value = false;
  }
}

const editing = ref(false);
const saving = ref(false);
const saveError = ref('');
const fieldErrors = ref<Record<string, string[]>>({});
const err = (f: string) => {
  const m = fieldErrors.value[f];
  return m?.length ? { error: true, errorMessage: m.join(' ') } : {};
};
const form = reactive({ id: '', name: '', description: '', priority: 100, cidrs: [] as string[], builtin: false });

function openEdit(z: ZoneAdmin | null) {
  Object.assign(
    form,
    z
      ? {
          id: z.id,
          name: z.name,
          description: z.description,
          priority: z.priority,
          cidrs: [...z.cidrs],
          builtin: z.builtin,
        }
      : { id: '', name: '', description: '', priority: 100, cidrs: [], builtin: false },
  );
  saveError.value = '';
  fieldErrors.value = {};
  editing.value = true;
}

async function save() {
  saving.value = true;
  saveError.value = '';
  fieldErrors.value = {};
  try {
    if (form.builtin) await updateZone(form.id, { description: form.description.trim() });
    else {
      const body = {
        name: form.name.trim(),
        description: form.description.trim(),
        priority: Number(form.priority) || 0,
        cidrs: form.cidrs.map((c) => c.trim()).filter(Boolean),
      };
      if (form.id) await updateZone(form.id, body);
      else await createZone(body);
    }
    editing.value = false;
    $q.notify({ type: 'positive', message: `Saved zone ${form.name}` });
    await load();
  } catch (e) {
    if (e instanceof ApiError) fieldErrors.value = e.fieldErrors;
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

function confirmDelete(z: ZoneAdmin) {
  $q.dialog({
    title: 'Delete zone',
    message: `Delete ${z.name}? Catalog items that reference it lose this zone.`,
    cancel: true,
    ok: { label: 'Delete', color: 'negative' },
  }).onOk(() => {
    void deleteZone(z.id)
      .then(load)
      .catch((e: unknown) => $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) }));
  });
}

const ip = ref('');
const testing = ref(false);
const testResult = ref<TestIpResult | null>(null);
const testError = ref('');
async function runTest() {
  testing.value = true;
  testError.value = '';
  testResult.value = null;
  try {
    testResult.value = await testIp(ip.value.trim());
  } catch (e) {
    testError.value = e instanceof Error ? e.message : String(e);
  } finally {
    testing.value = false;
  }
}

onMounted(load);
</script>
