<!--
  /settings: the app-wide default dashboard (GLOBAL only) and SSH handler (super admins change them; everyone else
  sees them read-only), config export / merge-import (super admins), and links to the admin pages.
-->
<template>
  <q-page class="q-pa-lg q-gutter-y-lg">
    <div class="text-h5">Application Settings</div>
    <div v-if="!session.isSuperAdmin" class="text-caption text-grey-7" data-testid="settings-read-only">
      Only super admins can change these settings.
    </div>

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
            :disable="!session.isSuperAdmin"
            data-testid="default-dashboard"
            v-bind="field"
          />
          <div v-if="session.isSuperAdmin" class="col-auto">
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

    <q-card flat bordered>
      <q-card-section class="text-subtitle1">SSH system handler</q-card-section>
      <q-card-section class="q-pt-none">
        <div class="text-caption text-grey-7 q-mb-sm">
          Lets users open SSH items in PuTTY or OpenSSH with one click, through a per-user URI handler they set up on
          their User Settings page. Turned off, SSH items only offer "copy command" and the setup instructions are
          hidden.
        </div>
        <div class="row q-col-gutter-md items-center">
          <q-toggle
            v-model="sshEnabled"
            class="col-12 col-sm-4"
            label="Enabled"
            color="positive"
            :disable="!session.isSuperAdmin"
            data-testid="ssh-uri-enabled"
          />
          <q-input
            v-model="sshScheme"
            class="col-12 col-sm-4"
            label="URI scheme"
            hint="Changing it means users re-run the setup"
            :disable="!session.isSuperAdmin || !sshEnabled"
            data-testid="ssh-uri-scheme"
            v-bind="field"
          />
          <div v-if="session.isSuperAdmin" class="col-auto">
            <q-btn color="primary" label="Save" :loading="savingSsh" :disable="!sshDirty" @click="saveSsh" />
          </div>
        </div>
        <q-banner v-if="sshError" class="bg-negative text-white q-mt-md" rounded dense>{{ sshError }}</q-banner>
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
      </q-list>
    </q-card>

    <q-card v-if="session.isSuperAdmin" flat bordered data-testid="config-card">
      <q-card-section class="text-subtitle1">Configuration</q-card-section>
      <q-card-section class="q-pt-none">
        <div class="text-caption text-grey-7 q-mb-sm">
          Sites, teams, zones, catalog items and lists (including personal) as JSON. Import merges a file into this
          install: new records are added and matching ones updated; nothing is deleted. You see every change before it
          is applied.
        </div>
        <div class="row q-gutter-sm">
          <q-btn
            outline
            color="primary"
            icon="download"
            label="Export config"
            type="a"
            :href="appPath(CONFIG_EXPORT_PATH)"
            download
            data-testid="config-export"
          />
          <q-btn
            outline
            color="primary"
            icon="upload"
            label="Import config"
            :loading="previewing"
            data-testid="config-import"
            @click="fileInput?.click()"
          />
          <input
            ref="fileInput"
            type="file"
            accept=".json,application/json"
            class="hidden"
            data-testid="config-file"
            @change="onFile"
          />
        </div>
        <q-banner v-if="importError" class="bg-negative text-white q-mt-md" rounded dense>{{ importError }}</q-banner>
      </q-card-section>
    </q-card>

    <q-dialog v-model="previewOpen" persistent>
      <q-card v-if="preview" style="width: 820px; max-width: 95vw" data-testid="config-preview">
        <q-card-section class="text-h6">Import config: review changes</q-card-section>
        <q-card-section class="q-pt-none">
          <q-markup-table flat bordered dense>
            <thead>
              <tr>
                <th class="text-left">Section</th>
                <th class="text-right">Added</th>
                <th class="text-right">Changed</th>
                <th class="text-right">Unchanged</th>
                <th class="text-right">Conflicts</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sec in CONFIG_SECTIONS" :key="sec">
                <td>{{ CONFIG_SECTION_LABELS[sec] }}</td>
                <td class="text-right">{{ preview.summary[sec]?.added ?? 0 }}</td>
                <td class="text-right">{{ preview.summary[sec]?.changed ?? 0 }}</td>
                <td class="text-right">{{ preview.summary[sec]?.unchanged ?? 0 }}</td>
                <td class="text-right">{{ preview.summary[sec]?.conflicts ?? 0 }}</td>
              </tr>
            </tbody>
          </q-markup-table>
        </q-card-section>
        <q-card-section v-if="preview.warnings.length" class="q-pt-none">
          <q-banner class="bg-orange-2 text-grey-9" rounded dense>
            <div v-for="w in preview.warnings" :key="w" class="text-caption">{{ w }}</div>
          </q-banner>
        </q-card-section>
        <q-card-section class="q-pt-none" style="max-height: 45vh; overflow-y: auto">
          <div v-if="preview.changes.length === 0" class="text-grey-7">
            Nothing to change: this install matches the file.
          </div>
          <template v-for="sec in CONFIG_SECTIONS" :key="sec">
            <q-list v-if="changesIn(sec).length" dense bordered separator class="q-mb-sm">
              <q-item-label header>{{ CONFIG_SECTION_LABELS[sec] }}</q-item-label>
              <q-item v-for="c in changesIn(sec)" :key="`${c.section}-${c.id}`" data-testid="config-change">
                <q-item-section side>
                  <q-badge :color="ACTION_COLORS[c.action]" :label="c.action" />
                </q-item-section>
                <q-item-section>
                  <q-item-label>{{ c.label }}</q-item-label>
                  <q-item-label v-if="c.action === 'UPDATE' && c.fields?.length" caption>
                    Changes: {{ c.fields.join(', ') }}
                  </q-item-label>
                  <q-item-label v-if="c.action === 'CONFLICT' && c.reason" caption class="text-warning">
                    Skipped: {{ c.reason }}
                  </q-item-label>
                </q-item-section>
              </q-item>
            </q-list>
          </template>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat label="Cancel" />
          <q-btn
            color="primary"
            :label="`Import ${applicable} change${applicable === 1 ? '' : 's'}`"
            :disable="applicable === 0"
            :loading="importing"
            data-testid="config-apply"
            @click="confirmImport"
          />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useQuasar } from 'quasar';
import { appPath } from '@/api/basePath';
import {
  applyConfigImport,
  CONFIG_EXPORT_PATH,
  CONFIG_SECTION_LABELS,
  CONFIG_SECTIONS,
  previewConfigImport,
  type ConfigChange,
  type ConfigSection,
  type ImportPreview,
} from '@/api/config';
import { ApiError } from '@/api/http';
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
    sshEnabled.value = s.ssh_uri_enabled;
    sshScheme.value = s.ssh_uri_scheme;
    sshSaved.value = { enabled: s.ssh_uri_enabled, scheme: s.ssh_uri_scheme };
    dashboardOptions.value = d.results.map((x) => ({ label: x.title, value: x.id }));
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

const sshEnabled = ref(true);
const sshScheme = ref('panic-ssh');
const sshSaved = ref({ enabled: true, scheme: 'panic-ssh' });
const sshDirty = computed(
  () => sshEnabled.value !== sshSaved.value.enabled || sshScheme.value.trim() !== sshSaved.value.scheme,
);
const savingSsh = ref(false);
const sshError = ref('');

async function saveSsh() {
  savingSsh.value = true;
  sshError.value = '';
  try {
    await updateSettings(version.value, { ssh_uri_enabled: sshEnabled.value, ssh_uri_scheme: sshScheme.value.trim() });
    $q.notify({ type: 'positive', message: 'SSH handler setting saved' });
    await load();
  } catch (e) {
    sshError.value = e instanceof Error ? e.message : String(e);
  } finally {
    savingSsh.value = false;
  }
}

async function save() {
  if (!dashboardId.value) return;
  saving.value = true;
  error.value = '';
  try {
    await updateSettings(version.value, { default_global_dashboard_id: dashboardId.value });
    $q.notify({ type: 'positive', message: 'Default dashboard updated' });
    await Promise.all([load(), session.fetchBootstrap()]);
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

// ---- config export / merge-import (super admin)
const ACTION_COLORS: Record<ConfigChange['action'], string> = {
  ADD: 'positive',
  UPDATE: 'primary',
  CONFLICT: 'orange',
};
const fileInput = ref<HTMLInputElement | null>(null);
const importDoc = ref<unknown>(null);
const preview = ref<ImportPreview | null>(null);
const previewOpen = ref(false);
const previewing = ref(false);
const importing = ref(false);
const importError = ref('');
const applicable = computed(() => preview.value?.changes.filter((c) => c.action !== 'CONFLICT').length ?? 0);
const changesIn = (section: ConfigSection) => preview.value?.changes.filter((c) => c.section === section) ?? [];

async function onFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = ''; // picking the same file again still fires `change`
  if (!file) return;
  importError.value = '';
  try {
    importDoc.value = JSON.parse(await file.text());
  } catch {
    importError.value = `${file.name} is not valid JSON.`;
    return;
  }
  await runPreview();
}

async function runPreview() {
  previewing.value = true;
  importError.value = '';
  try {
    preview.value = await previewConfigImport(importDoc.value);
    previewOpen.value = true;
  } catch (e) {
    importError.value = e instanceof Error ? e.message : String(e);
  } finally {
    previewing.value = false;
  }
}

function confirmImport() {
  const n = applicable.value;
  $q.dialog({
    title: 'Import config',
    message: `Apply ${n} change${n === 1 ? '' : 's'}? Nothing is deleted.`,
    cancel: true,
    ok: { label: 'Import', color: 'primary' },
  }).onOk(() => void runImport());
}

async function runImport() {
  if (!preview.value) return;
  importing.value = true;
  try {
    const res = await applyConfigImport(importDoc.value, preview.value.plan_digest);
    const total = CONFIG_SECTIONS.reduce(
      (sum, s) => sum + (res.summary[s]?.added ?? 0) + (res.summary[s]?.changed ?? 0),
      0,
    );
    $q.notify({ type: 'positive', message: `Config imported: ${total} change${total === 1 ? '' : 's'} applied` });
    previewOpen.value = false;
    preview.value = null;
    await Promise.all([load(), session.fetchBootstrap()]);
  } catch (e) {
    if (e instanceof ApiError && e.status === 409) {
      $q.dialog({
        title: 'Data changed',
        message: `${e.message} Review the changes again?`,
        cancel: true,
        ok: { label: 'Re-run preview', color: 'primary' },
      }).onOk(() => void runPreview());
      return;
    }
    $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
  } finally {
    importing.value = false;
  }
}

onMounted(load);
</script>
