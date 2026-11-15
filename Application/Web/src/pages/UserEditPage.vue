<!--
  /settings/users/<id> (T-S6-11): display name, manual permissions, team membership, enable / disable, View As.
  `/rbac` redirects to the users list.
-->
<template>
  <q-page class="q-pa-lg">
    <div v-if="loading" class="flex flex-center q-pa-xl"><q-spinner size="xl" /></div>
    <q-banner v-else-if="loadError" class="bg-negative text-white" rounded>{{ loadError }}</q-banner>
    <template v-else-if="user">
      <div class="row items-center q-mb-md q-gutter-x-sm">
        <q-btn flat round dense icon="arrow_back" :to="{ name: 'settings-users' }" aria-label="Back to users" />
        <div class="text-h5">{{ user.username }}</div>
        <q-badge outline color="grey-7" :label="user.auth_source" />
        <q-badge :color="user.disabled ? 'grey-6' : 'positive'" :label="user.disabled ? 'Disabled' : 'Active'" />
        <q-space />
        <q-btn
          v-if="session.canViewAs && !user.disabled && user.id !== session.me?.id"
          outline
          color="primary"
          icon="visibility"
          label="View as"
          @click="viewAs"
        />
      </div>

      <div class="row q-col-gutter-lg">
        <div class="col-12 col-md-7">
          <q-card flat bordered>
            <q-form @submit="save">
              <q-card-section class="row q-col-gutter-md">
                <q-input v-model="form.display_name" class="col-12" label="Display name" v-bind="field" />
                <div class="col-12">
                  <div class="text-subtitle2 q-mb-xs">Permissions</div>
                  <q-option-group v-model="form.permissions" type="checkbox" :options="permissionOptions" inline />
                </div>
                <q-select
                  v-model="form.team_ids"
                  class="col-12"
                  :options="teamOptions"
                  label="Team membership"
                  multiple
                  use-chips
                  emit-value
                  map-options
                  v-bind="field"
                />
                <q-toggle v-model="form.enabled" class="col-12" label="Account enabled" color="positive" />
                <div v-if="saveError" class="col-12">
                  <q-banner class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
                </div>
              </q-card-section>
              <q-card-actions align="right">
                <q-btn flat label="Reset" :disable="!dirty" @click="fill(user)" />
                <q-btn type="submit" color="primary" label="Save" :loading="saving" :disable="!dirty" />
              </q-card-actions>
            </q-form>
          </q-card>
        </div>
        <div class="col-12 col-md-5">
          <q-card flat bordered>
            <q-card-section class="text-subtitle2">Owns</q-card-section>
            <q-list dense>
              <q-item
                ><q-item-section>Personal catalog items</q-item-section
                ><q-item-section side>{{ user.owned_counts.catalog }}</q-item-section></q-item
              >
              <q-item
                ><q-item-section>Personal lists</q-item-section
                ><q-item-section side>{{ user.owned_counts.lists }}</q-item-section></q-item
              >
              <q-item
                ><q-item-section>Personal dashboards</q-item-section
                ><q-item-section side>{{ user.owned_counts.dashboards }}</q-item-section></q-item
              >
            </q-list>
            <q-separator />
            <q-card-section class="text-caption text-grey-7">
              Last sign-in: {{ user.last_login_at ? new Date(user.last_login_at).toLocaleString() : 'never' }}
            </q-card-section>
          </q-card>
        </div>
      </div>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import { listCodeNamed, type CodeNamed } from '@/api/admin';
import { getUser, PERMISSION_FLAGS, PERMISSION_LABELS, updateUser, type UserDetail } from '@/api/users';
import { useSessionStore } from '@/stores/session';

const props = defineProps<{ id: string }>();

const $q = useQuasar();
const router = useRouter();
const session = useSessionStore();

const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const permissionOptions = PERMISSION_FLAGS.map((p) => ({ label: PERMISSION_LABELS[p], value: p }));

const user = ref<UserDetail | null>(null);
const teams = ref<CodeNamed[]>([]);
const teamOptions = computed(() => teams.value.map((t) => ({ label: `${t.code} - ${t.name}`, value: t.id })));
const loading = ref(false);
const loadError = ref('');
const saving = ref(false);
const saveError = ref('');
const form = reactive({ display_name: '', permissions: [] as string[], team_ids: [] as string[], enabled: true });

function fill(u: UserDetail) {
  Object.assign(form, {
    display_name: u.display_name,
    permissions: [...u.permissions],
    team_ids: [...u.team_ids],
    enabled: !u.disabled,
  });
}

const sameSet = (a: string[], b: string[]) => a.length === b.length && a.every((x) => b.includes(x));
const dirty = computed(
  () =>
    !!user.value &&
    (form.display_name !== user.value.display_name ||
      !sameSet(form.permissions, user.value.permissions) ||
      !sameSet(form.team_ids, user.value.team_ids) ||
      form.enabled === user.value.disabled),
);

async function load() {
  loading.value = true;
  loadError.value = '';
  try {
    const [u, t] = await Promise.all([getUser(props.id), listCodeNamed('teams')]);
    user.value = u;
    teams.value = t;
    fill(u);
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
watch(() => props.id, load, { immediate: true });

async function save() {
  const u = user.value;
  if (!u) return;
  saving.value = true;
  saveError.value = '';
  try {
    await updateUser(u.id, u.version, {
      display_name: form.display_name.trim(),
      permissions: form.permissions as UserDetail['permissions'],
      team_ids: form.team_ids,
      disabled: !form.enabled,
    });
    $q.notify({ type: 'positive', message: `Saved ${u.username}` });
    await load();
    if (u.id === session.me?.id) await session.fetchBootstrap(); // own permissions changed
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

async function viewAs() {
  if (!user.value) return;
  try {
    await session.startViewAs({ userId: user.value.id });
    await router.push({ name: 'root' });
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
  }
}
</script>
