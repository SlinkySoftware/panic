<template>
  <q-layout view="hHh Lpr lFf">
    <q-header elevated class="panic-header text-dark">
      <q-toolbar>
        <q-btn flat dense round icon="menu" aria-label="Toggle navigation" @click="drawerOpen = !drawerOpen" />
        <q-icon name="shield" size="sm" class="q-ml-sm q-mr-xs" color="primary" />
        <q-toolbar-title>PANIC</q-toolbar-title>
        <q-btn
          flat
          dense
          no-caps
          icon="search"
          label="Search"
          class="q-mr-sm"
          data-testid="open-palette"
          @click="palette?.show()"
        >
          <q-tooltip>Search and launch (Ctrl+K or /)</q-tooltip>
        </q-btn>

        <div
          v-if="session.zone"
          class="panic-zone-badge q-mr-sm"
          :class="{ 'panic-zone-badge--default': isDefaultZone }"
          data-testid="zone-badge"
        >
          <q-icon name="location_on" size="16px" />
          <span>{{ session.zone.name }}</span>
          <q-tooltip v-if="isDefaultZone">No Zone CIDR matched your location; using the Default zone.</q-tooltip>
        </div>

        <q-btn
          v-if="session.canViewAs"
          flat
          dense
          no-caps
          icon="visibility"
          label="View As"
          class="q-mr-sm"
          data-testid="view-as-switcher"
          @click="openViewAsDialog"
        />

        <q-btn
          flat
          round
          dense
          :icon="ui.densityIcon"
          :aria-label="ui.densityLabel"
          data-testid="density-toggle"
          @click="ui.toggleDensity()"
        >
          <q-tooltip>{{ ui.densityLabel }}</q-tooltip>
        </q-btn>

        <q-btn
          flat
          round
          dense
          :icon="ui.themeIcon"
          :aria-label="ui.themeLabel"
          data-testid="theme-toggle"
          @click="ui.cycleTheme()"
        >
          <q-tooltip>{{ ui.themeLabel }}</q-tooltip>
        </q-btn>

        <q-btn-dropdown flat no-caps icon="account_circle" :label="displayName" class="q-ml-sm" data-testid="user-menu">
          <q-list style="min-width: 200px">
            <q-item>
              <q-item-section>
                <q-item-label>{{ displayName }}</q-item-label>
                <q-item-label caption>{{ session.isAdmin ? 'Global Admin' : 'User' }}</q-item-label>
              </q-item-section>
            </q-item>
            <q-separator />
            <q-item v-close-popup clickable :to="{ name: 'profile' }">
              <q-item-section avatar><q-icon name="account_circle" /></q-item-section>
              <q-item-section>Profile</q-item-section>
            </q-item>
            <q-item v-close-popup clickable data-testid="logout" @click="onLogout">
              <q-item-section avatar><q-icon name="logout" /></q-item-section>
              <q-item-section>Sign out</q-item-section>
            </q-item>
          </q-list>
        </q-btn-dropdown>
      </q-toolbar>

      <div
        v-if="session.isViewingAs"
        class="panic-view-as-banner q-px-md q-py-xs row items-center"
        data-testid="view-as-banner"
      >
        <q-icon name="visibility" class="q-mr-sm" />
        <span
          >Viewing as <strong>{{ session.me?.display_name }}</strong> ({{ session.me?.username }})</span
        >
        <q-space />
        <q-btn flat dense no-caps label="Stop View As" data-testid="stop-view-as" @click="onExitViewAs" />
      </div>
    </q-header>

    <q-drawer
      v-model="drawerOpen"
      show-if-above
      bordered
      :width="232"
      :mini-width="64"
      :mini="!railPinned && !railExpanded"
      class="panic-rail"
      @mouseenter="railExpanded = true"
      @mouseleave="railExpanded = false"
    >
      <q-list padding data-testid="nav" style="padding-bottom: 64px">
        <q-item-label header class="panic-nav-heading">Dashboards</q-item-label>
        <q-item
          v-for="d in session.navDashboards"
          :key="d.id"
          v-ripple
          clickable
          :to="{ name: 'dashboard-view', params: { id: d.id } }"
          active-class="text-primary"
          :data-testid="`nav-dashboard-${d.id}`"
        >
          <q-item-section avatar><q-icon :name="d.icon || 'dashboard'" /></q-item-section>
          <q-item-section>{{ d.title }}</q-item-section>
          <q-item-section v-if="d.default" side>
            <q-icon name="star" size="16px" color="amber">
              <q-tooltip>Your default dashboard</q-tooltip>
            </q-icon>
          </q-item-section>
          <q-item-section v-if="d.locked" side>
            <q-icon name="push_pin" size="16px">
              <q-tooltip>Pinned (cannot be removed from the menu)</q-tooltip>
            </q-icon>
          </q-item-section>
        </q-item>
        <q-item clickable :disable="session.isViewingAs" data-testid="nav-add-dashboard" @click="newDashboard = true">
          <q-item-section avatar><q-icon name="add" /></q-item-section>
          <q-item-section>Add dashboard</q-item-section>
        </q-item>

        <template v-for="group in navGroups" :key="group.title">
          <q-separator class="q-my-sm" />
          <q-item-label header class="panic-nav-heading">{{ group.title }}</q-item-label>
          <q-item
            v-for="link in group.links"
            :key="link.name"
            v-ripple
            clickable
            :to="link.to"
            active-class="text-primary"
            :data-testid="`nav-${link.name}`"
          >
            <q-item-section avatar><q-icon :name="link.icon" /></q-item-section>
            <q-item-section>{{ link.title }}</q-item-section>
          </q-item>
        </template>
      </q-list>
      <q-list class="absolute-bottom q-pb-sm">
        <q-item clickable data-testid="nav-pin" @click="toggleRailPinned">
          <q-item-section avatar>
            <q-icon
              name="push_pin"
              :color="railPinned ? 'primary' : undefined"
              :class="{ 'panic-unpinned': !railPinned }"
            />
          </q-item-section>
          <q-item-section>{{ railPinned ? 'Unpin menu' : 'Keep menu open' }}</q-item-section>
          <q-tooltip v-if="!railPinned" anchor="center right" self="center left">Keep menu open</q-tooltip>
        </q-item>
      </q-list>
    </q-drawer>

    <AddDashboardDialog v-model="newDashboard" />
    <CommandPalette ref="palette" />

    <q-page-container>
      <router-view />
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { Dialog, LocalStorage } from 'quasar';
import { useRouter } from 'vue-router';
import { navGroupsFor } from '@/router/nav';
import AddDashboardDialog from '@/components/dashboard/AddDashboardDialog.vue';
import CommandPalette from '@/components/palette/CommandPalette.vue';
import { useSessionStore } from '@/stores/session';
import { useUiStore } from '@/stores/theme';

const session = useSessionStore();
const ui = useUiStore();
const router = useRouter();

const drawerOpen = ref(true);
const newDashboard = ref(false);
const palette = ref<InstanceType<typeof CommandPalette> | null>(null);
const railExpanded = ref(true);
// Pinned = the rail stays expanded instead of collapsing to icons when the pointer leaves; remembered per browser.
const NAV_PINNED_KEY = 'panic.navPinned';
const railPinned = ref(LocalStorage.getItem(NAV_PINNED_KEY) === true);
function toggleRailPinned(): void {
  railPinned.value = !railPinned.value;
  LocalStorage.set(NAV_PINNED_KEY, railPinned.value);
}

const displayName = computed(() => session.me?.display_name ?? session.me?.username ?? '');
const isDefaultZone = computed(() => session.zoneSource === 'DEFAULT');
const navGroups = computed(() => navGroupsFor(session.isAdmin));

function openViewAsDialog(): void {
  Dialog.create({
    title: 'View As',
    message: 'Enter the user id to view the portal as (Settings → Users has the full picker later).',
    prompt: { model: '', type: 'text', isValid: (v: string) => v.trim().length > 0 },
    cancel: true,
    persistent: true,
  }).onOk((userId: string) => {
    void session.startViewAs(userId.trim()).then(() => router.push({ name: 'root' }));
  });
}

async function onExitViewAs(): Promise<void> {
  await session.exitViewAs();
  await router.push({ name: 'root' });
}

async function onLogout(): Promise<void> {
  try {
    await session.logout();
  } finally {
    await router.push({ name: 'login' });
  }
}
</script>

<style scoped>
.panic-unpinned {
  transform: rotate(45deg);
  opacity: 0.6;
}
</style>
