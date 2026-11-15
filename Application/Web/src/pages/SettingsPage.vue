<!-- /settings (T-S6-11): the app-wide default dashboard (GLOBAL only), export, and links to the admin pages. -->
<template>
  <q-page class="q-pa-lg q-gutter-y-lg">
    <div class="text-h5">Settings</div>

    <q-card flat bordered>
      <q-card-section class="text-subtitle1">Default dashboard for everyone</q-card-section>
      <q-card-section class="q-pt-none">
        <div class="text-caption text-grey-7 q-mb-sm">
          Shown to users who have not chosen their own default. Must be a GLOBAL dashboard; it is always in every menu.
        </div>
        <div class="row q-col-gutter-md items-center">
          <q-select
            v-model="dashboardId"
            class="col-12 col-sm-6"
            :options="dashboardOptions"
            label="Dashboard"
            emit-value
            map-options
            :disable="!session.isAdmin"
            v-bind="field"
          />
          <div v-if="session.isAdmin" class="col-auto">
            <q-btn
              color="primary"
              label="Save"
              :loading="saving"
              :disable="!dashboardId || dashboardId === current"
              @click="save"
            />
          </div>
        </div>
        <q-banner v-if="error" class="bg-negative text-white q-mt-md" rounded dense>{{ error }}</q-banner>
      </q-card-section>
    </q-card>

    <q-card v-if="session.isAdmin" flat bordered>
      <q-card-section class="text-subtitle1">Administration</q-card-section>
      <q-list separator>
        <q-item v-for="l in links" :key="l.to" clickable :to="{ name: l.to }">
          <q-item-section avatar><q-icon :name="l.icon" /></q-item-section>
          <q-item-section>
            <q-item-label>{{ l.label }}</q-item-label>
            <q-item-label caption>{{ l.caption }}</q-item-label>
          </q-item-section>
        </q-item>
        <q-item clickable tag="a" href="/api/v1/export">
          <q-item-section avatar><q-icon name="download" /></q-item-section>
          <q-item-section>
            <q-item-label>Export</q-item-label>
            <q-item-label caption>Download everything as portable JSON</q-item-label>
          </q-item-section>
        </q-item>
      </q-list>
    </q-card>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import { listDashboards } from '@/api/dashboards';
import { getSettings, updateSettings } from '@/api/settings';
import { useSessionStore } from '@/stores/session';

const $q = useQuasar();
const session = useSessionStore();
const field = { outlined: true, dense: true, hideBottomSpace: true } as const;

const links = [
  {
    to: 'settings-users',
    icon: 'people',
    label: 'Users',
    caption: 'Permissions, team membership, enable / disable, View As',
  },
  { to: 'settings-orphans', icon: 'link_off', label: 'Orphans', caption: 'Resources left without a team or owner' },
  { to: 'audit', icon: 'history', label: 'Audit', caption: 'Who changed what, and when' },
  {
    to: 'settings-client-ip',
    icon: 'lan',
    label: 'Client-IP diagnostics',
    caption: 'Proxy trust chain and zone resolution',
  },
];

const dashboardOptions = ref<{ label: string; value: string }[]>([]);
const dashboardId = ref<string | null>(null);
const current = ref<string | null>(null);
const version = ref(0);
const saving = ref(false);
const error = ref('');

async function load() {
  error.value = '';
  try {
    const [s, d] = await Promise.all([getSettings(), listDashboards({ scope: 'GLOBAL' })]);
    current.value = s.default_global_dashboard?.id ?? null;
    dashboardId.value = current.value;
    version.value = s.version;
    dashboardOptions.value = d.results.map((x) => ({ label: x.title, value: x.id }));
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function save() {
  if (!dashboardId.value) return;
  saving.value = true;
  error.value = '';
  try {
    await updateSettings(version.value, dashboardId.value);
    $q.notify({ type: 'positive', message: 'Default dashboard updated' });
    await Promise.all([load(), session.fetchBootstrap()]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
