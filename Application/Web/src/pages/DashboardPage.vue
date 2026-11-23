<!--
  /dashboard/<id> locked view: 12-column grid of HOST and LIST widgets, pin / default actions.
  Re-entering a dashboard revalidates with If-None-Match.
-->
<template>
  <q-page class="q-pa-md">
    <div v-if="loading && !view" class="flex flex-center q-pa-xl"><q-spinner size="xl" /></div>
    <q-banner v-else-if="error" class="bg-negative text-white" rounded>{{ error }}</q-banner>
    <template v-else-if="view">
      <div class="row items-center q-mb-md q-gutter-x-sm">
        <div class="text-h5">{{ view.dashboard.title }}</div>
        <q-badge :color="scopeColor[view.dashboard.scope]" :label="view.dashboard.scope" />
        <q-space />
        <q-btn
          flat
          round
          :icon="view.dashboard.is_user_default ? 'star' : 'star_border'"
          :color="view.dashboard.is_user_default ? 'amber-8' : undefined"
          :disable="session.isViewingAs"
          @click="toggleDefault"
        >
          <q-tooltip>{{
            view.dashboard.is_user_default ? 'Your default (click to reset)' : 'Make my default'
          }}</q-tooltip>
        </q-btn>
        <q-btn
          flat
          round
          icon="push_pin"
          :color="pinned ? 'primary' : 'grey-6'"
          :disable="session.isViewingAs"
          @click="togglePin"
        >
          <q-tooltip>{{ pinned ? 'Unpin from menu' : 'Pin to menu' }}</q-tooltip>
        </q-btn>
        <q-btn
          v-if="view.dashboard.can_edit"
          outline
          color="primary"
          icon="edit"
          label="Edit"
          :to="{ name: 'dashboard-edit', params: { id: view.dashboard.id } }"
        />
      </div>
      <div v-if="view.dashboard.description" class="text-body2 text-grey-7 q-mb-md">
        {{ view.dashboard.description }}
      </div>

      <div v-if="view.widgets.length" class="panic-grid">
        <div
          v-for="w in view.widgets"
          :key="w.id"
          :style="{ gridColumn: `${w.grid_x} / span ${w.grid_w}`, gridRow: `${w.grid_y} / span ${w.grid_h}` }"
        >
          <DashboardWidget :widget="w" :items="view.items" :lists="view.lists" />
        </div>
      </div>
      <q-banner v-else rounded class="bg-grey-2 text-grey-8">
        This dashboard has no widgets yet.
        <span v-if="view.dashboard.can_edit">Use <b>Edit</b> to add hosts and lists.</span>
      </q-banner>
    </template>
  </q-page>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import type { Scope } from '@/api/catalog';
import {
  getDashboardView,
  pinDashboard,
  setMyDefaultDashboard,
  unpinDashboard,
  type DashboardView,
} from '@/api/dashboards';
import DashboardWidget from '@/components/dashboard/DashboardWidget.vue';
import { useSessionStore } from '@/stores/session';

const props = defineProps<{ id: string }>();

const $q = useQuasar();
const session = useSessionStore();
const scopeColor: Record<Scope, string> = { GLOBAL: 'primary', TEAM: 'teal', PERSONAL: 'grey-7' };

const view = ref<DashboardView | null>(null);
const loading = ref(false);
const error = ref('');

const pinned = computed(() => session.navDashboards.some((d) => d.id === props.id));

async function load() {
  loading.value = true;
  error.value = '';
  try {
    view.value = await getDashboardView(props.id);
  } catch (e) {
    view.value = null;
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

async function act(fn: () => Promise<unknown>, ok: string) {
  try {
    await fn();
    await Promise.all([session.fetchBootstrap(), load()]);
    $q.notify({ type: 'positive', message: ok });
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
  }
}

const toggleDefault = () =>
  view.value?.dashboard.is_user_default
    ? act(() => setMyDefaultDashboard(null), 'Default reset')
    : act(() => setMyDefaultDashboard(props.id), 'Set as your default');

const togglePin = () =>
  pinned.value ? act(() => unpinDashboard(props.id), 'Unpinned') : act(() => pinDashboard(props.id), 'Pinned');

watch(() => props.id, load, { immediate: true });
</script>

<style scoped>
.panic-grid {
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  grid-auto-rows: 140px;
  gap: 12px;
}
@media (max-width: 800px) {
  .panic-grid {
    grid-template-columns: 1fr;
  }
  .panic-grid > div {
    grid-column: auto !important;
  }
}
</style>
