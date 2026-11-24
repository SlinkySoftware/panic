<!-- /settings/users: search, filters, pre-provision, disable / enable. Row click opens the user. -->
<template>
  <q-page class="q-pa-lg">
    <q-table
      v-model:pagination="pagination"
      flat
      bordered
      title="Users"
      :rows="rows"
      :columns="columns"
      row-key="id"
      :loading="loading"
      :rows-per-page-options="[25, 50, 100]"
      @request="onRequest"
      @row-click="(_e, row) => router.push({ name: 'settings-user-detail', params: { id: row.id } })"
    >
      <template #top-right>
        <div class="row q-gutter-sm items-center">
          <q-select
            v-model="permission"
            :options="permissionOptions"
            label="Permission"
            emit-value
            map-options
            clearable
            style="min-width: 170px"
            v-bind="field"
          />
          <q-select
            v-model="teamId"
            :options="teamOptions"
            label="Team"
            emit-value
            map-options
            clearable
            style="min-width: 130px"
            v-bind="field"
          />
          <q-select
            v-model="status"
            :options="statusOptions"
            label="Status"
            emit-value
            map-options
            clearable
            style="min-width: 120px"
            v-bind="field"
          />
          <q-input v-model="q" placeholder="Search" debounce="300" clearable v-bind="field">
            <template #prepend><q-icon name="search" /></template>
          </q-input>
          <q-btn color="primary" icon="person_add" label="Add user" @click="openCreate" />
        </div>
      </template>
      <template #body-cell-username="cell">
        <q-td :props="cell">
          {{ cell.row.username }}
          <q-badge v-if="cell.row.bootstrap_admin" color="deep-purple" label="Bootstrap admin" class="q-ml-xs" />
        </q-td>
      </template>
      <template #body-cell-permissions="cell">
        <q-td :props="cell">
          <q-badge
            v-for="p in cell.row.permissions"
            :key="p"
            :color="p === 'SUPER_ADMIN' ? 'deep-purple' : p === 'GLOBAL_ADMIN' ? 'red-7' : 'primary'"
            class="q-mr-xs"
          >
            {{ PERMISSION_LABELS[p as PermissionFlag] ?? p }}
          </q-badge>
        </q-td>
      </template>
      <template #body-cell-disabled="cell">
        <q-td :props="cell">
          <q-badge
            :color="cell.row.disabled ? 'grey-6' : 'positive'"
            :label="cell.row.disabled ? 'Disabled' : 'Active'"
          />
        </q-td>
      </template>
      <template #body-cell-actions="cell">
        <q-td :props="cell" class="text-right">
          <q-btn
            v-if="cell.row.can_edit !== false && !cell.row.bootstrap_admin"
            flat
            dense
            no-caps
            :label="cell.row.disabled ? 'Enable' : 'Disable'"
            :color="cell.row.disabled ? 'positive' : 'negative'"
            @click.stop="toggleDisabled(cell.row)"
          />
        </q-td>
      </template>
    </q-table>

    <q-dialog v-model="creating" persistent>
      <q-card style="width: 480px; max-width: 95vw">
        <q-form @submit="create">
          <q-card-section class="text-h6">Add user</q-card-section>
          <q-card-section class="row q-col-gutter-md">
            <div class="col-12 text-caption text-grey-7">
              Pre-provision an account so permissions and teams are ready before the first sign-in (no password; users
              sign in through LDAP or SSO).
            </div>
            <q-input
              v-model="newUser.username"
              class="col-12 col-sm-6"
              label="Username"
              autofocus
              :rules="[required]"
              v-bind="{ ...field, ...err('username') }"
            />
            <q-input v-model="newUser.display_name" class="col-12 col-sm-6" label="Display name" v-bind="field" />
            <q-select
              v-model="newUser.permissions"
              class="col-12"
              :options="permissionOptions"
              label="Permissions"
              multiple
              use-chips
              emit-value
              map-options
              v-bind="field"
            />
            <q-select
              v-model="newUser.team_ids"
              class="col-12"
              :options="teamOptions"
              label="Teams"
              multiple
              use-chips
              emit-value
              map-options
              v-bind="field"
            />
            <div v-if="saveError" class="col-12">
              <q-banner class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
            </div>
          </q-card-section>
          <q-card-actions align="right">
            <q-btn v-close-popup flat label="Cancel" />
            <q-btn type="submit" color="primary" label="Create" :loading="saving" />
          </q-card-actions>
        </q-form>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar, type QTableColumn, type QTableProps } from 'quasar';
import { listCodeNamed, type CodeNamed } from '@/api/admin';
import { ApiError } from '@/api/http';
import {
  createUser,
  listUsers,
  PERMISSION_LABELS,
  permissionFlagsFor,
  updateUser,
  type PermissionFlag,
  type UserSummary,
} from '@/api/users';
import { useSessionStore } from '@/stores/session';

const $q = useQuasar();
const session = useSessionStore();
const router = useRouter();

const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const required = (v: string) => (!!v && v.trim().length > 0) || 'Required';

const teams = ref<CodeNamed[]>([]);
const teamName = computed(() => new Map(teams.value.map((t) => [t.id, t.code])));
const teamOptions = computed(() => teams.value.map((t) => ({ label: `${t.code} - ${t.name}`, value: t.id })));
const permissionOptions = computed(() =>
  permissionFlagsFor(session.isSuperAdmin).map((p) => ({ label: PERMISSION_LABELS[p], value: p })),
);
const statusOptions = [
  { label: 'Active', value: 'false' },
  { label: 'Disabled', value: 'true' },
];

const columns: QTableColumn<UserSummary>[] = [
  { name: 'username', label: 'Username', field: 'username', align: 'left' },
  { name: 'display_name', label: 'Display name', field: 'display_name', align: 'left' },
  { name: 'auth_source', label: 'Source', field: 'auth_source', align: 'left' },
  { name: 'permissions', label: 'Permissions', field: 'permissions', align: 'left' },
  {
    name: 'teams',
    label: 'Teams',
    field: 'team_ids',
    align: 'left',
    format: (ids: string[]) => ids.map((id) => teamName.value.get(id) ?? '?').join(', ') || '—',
  },
  { name: 'disabled', label: 'Status', field: 'disabled', align: 'left' },
  {
    name: 'last_login_at',
    label: 'Last sign-in',
    field: 'last_login_at',
    align: 'left',
    format: (v: string | null) => (v ? new Date(v).toLocaleString() : 'never'),
  },
  { name: 'actions', label: '', field: 'id', align: 'right' },
];

const rows = ref<UserSummary[]>([]);
const loading = ref(false);
const q = ref('');
const permission = ref<string | null>(null);
const teamId = ref<string | null>(null);
const status = ref<string | null>(null);
const pagination = ref({ sortBy: 'username', descending: false, page: 1, rowsPerPage: 25, rowsNumber: 0 });

async function onRequest(req: Parameters<NonNullable<QTableProps['onRequest']>>[0]) {
  const { page, rowsPerPage } = req.pagination;
  loading.value = true;
  try {
    const res = await listUsers({
      q: q.value ?? '',
      permission: permission.value ?? '',
      team_id: teamId.value ?? '',
      disabled: status.value ?? '',
      page,
      page_size: rowsPerPage,
    });
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
watch([q, permission, teamId, status], () => void reload(true));

function toggleDisabled(u: UserSummary) {
  const disabling = !u.disabled;
  $q.dialog({
    title: disabling ? 'Disable user' : 'Enable user',
    message: disabling
      ? `Disable ${u.username}? They are signed out at once, and their personal items become orphans.`
      : `Enable ${u.username}?`,
    cancel: true,
    ok: { label: disabling ? 'Disable' : 'Enable', color: disabling ? 'negative' : 'positive' },
  }).onOk(() => {
    void updateUser(u.id, u.version, { disabled: disabling })
      .then(() => reload())
      .catch((e: unknown) => $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) }));
  });
}

const creating = ref(false);
const saving = ref(false);
const saveError = ref('');
const fieldErrors = ref<Record<string, string[]>>({});
const err = (f: string) => {
  const m = fieldErrors.value[f];
  return m?.length ? { error: true, errorMessage: m.join(' ') } : {};
};
const newUser = reactive({ username: '', display_name: '', permissions: [] as string[], team_ids: [] as string[] });
function openCreate() {
  Object.assign(newUser, { username: '', display_name: '', permissions: [], team_ids: [] });
  saveError.value = '';
  fieldErrors.value = {};
  creating.value = true;
}
async function create() {
  saving.value = true;
  saveError.value = '';
  try {
    const u = await createUser({
      username: newUser.username.trim(),
      ...(newUser.display_name.trim() ? { display_name: newUser.display_name.trim() } : {}),
      permissions: newUser.permissions,
      team_ids: newUser.team_ids,
    });
    creating.value = false;
    await router.push({ name: 'settings-user-detail', params: { id: u.id } });
  } catch (e) {
    if (e instanceof ApiError) fieldErrors.value = e.fieldErrors;
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

onMounted(async () => {
  teams.value = await listCodeNamed('teams').catch(() => []);
  void reload();
});
</script>
