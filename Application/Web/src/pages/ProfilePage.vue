<!--
  /profile (T-S6-11): display name, remote user, SSH template, my default dashboard, density, theme and the
  unreachable policy. Writes act on the real signed-in user, so they are refused during View As.
-->
<template>
  <q-page class="q-pa-lg">
    <div class="text-h5 q-mb-md">Profile</div>
    <div v-if="!profile && !error" class="flex flex-center q-pa-xl"><q-spinner size="xl" /></div>
    <q-banner v-if="session.isViewingAs" class="bg-warning q-mb-md" rounded dense>
      You are viewing as another user; profile changes are disabled.
    </q-banner>
    <q-card v-if="profile" flat bordered style="max-width: 760px">
      <q-form @submit="save">
        <q-card-section class="row q-col-gutter-md">
          <q-input
            v-model="form.display_name"
            class="col-12 col-sm-6"
            label="Display name"
            v-bind="{ ...field, ...err('display_name') }"
          />
          <q-input
            v-model="form.default_remote_user"
            class="col-12 col-sm-6"
            label="Default remote user"
            hint="Used in SSH and RDP launches unless an item overrides it"
            v-bind="{ ...field, ...err('default_remote_user') }"
          />
          <SshTemplateField v-model="form.ssh_template" class="col-12" :error="fieldErrors.ssh_template?.join(' ')" />
          <q-select
            v-model="defaultDashboard"
            class="col-12 col-sm-6"
            :options="dashboardOptions"
            label="My default dashboard"
            emit-value
            map-options
            clearable
            v-bind="field"
          />
          <q-select
            v-model="form.unreachable_policy"
            class="col-12 col-sm-6"
            :options="unreachableOptions"
            label="Unreachable items"
            emit-value
            map-options
            v-bind="field"
          />
          <q-select
            v-model="form.density"
            class="col-12 col-sm-6"
            :options="['COMFORT', 'COMPACT']"
            label="Density"
            v-bind="field"
          />
          <q-select
            v-model="form.theme"
            class="col-12 col-sm-6"
            :options="['LIGHT', 'DARK']"
            label="Theme"
            v-bind="field"
          />
          <div v-if="saveError" class="col-12">
            <q-banner class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn type="submit" color="primary" label="Save" :loading="saving" :disable="session.isViewingAs" />
        </q-card-actions>
      </q-form>
    </q-card>
    <SshHandlerSetup
      v-if="sshScheme"
      class="q-mt-lg"
      style="max-width: 760px"
      :scheme="sshScheme"
      :preferred-client="
        presetFor(form.ssh_template) === 'putty' || presetFor(form.ssh_template) === 'plink' ? 'putty' : 'openssh'
      "
    />
    <q-banner v-if="error" class="bg-negative text-white" rounded>{{ error }}</q-banner>
  </q-page>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useQuasar } from 'quasar';
import { listDashboards, setMyDefaultDashboard } from '@/api/dashboards';
import { ApiError } from '@/api/http';
import { getMe, getSettings, updateMe, type MyProfile } from '@/api/settings';
import { useSessionStore } from '@/stores/session';
import { useUiStore } from '@/stores/theme';
import SshTemplateField from '@/components/profile/SshTemplateField.vue';
import SshHandlerSetup from '@/components/profile/SshHandlerSetup.vue';
import { presetFor } from '@/components/profile/sshPresets';

const $q = useQuasar();
const session = useSessionStore();
const ui = useUiStore();
const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const unreachableOptions = [
  { label: 'Dim them', value: 'DIM' },
  { label: 'Hide them', value: 'HIDE' },
];

const profile = ref<MyProfile | null>(null);
const error = ref('');
const saving = ref(false);
const saveError = ref('');
const fieldErrors = ref<Record<string, string[]>>({});
const err = (f: string) => {
  const m = fieldErrors.value[f];
  return m?.length ? { error: true, errorMessage: m.join(' ') } : {};
};
type Form = Pick<MyProfile, 'display_name' | 'default_remote_user' | 'ssh_template'> & MyProfile['prefs'];
const form = reactive<Form>({
  display_name: '',
  default_remote_user: '',
  ssh_template: '',
  density: 'COMFORT',
  theme: 'LIGHT',
  unreachable_policy: 'DIM',
});
const defaultDashboard = ref<string | null>(null);
// Scheme of the admin-enabled SSH URI handler; null hides the setup section.
const sshScheme = ref<string | null>(null);
const dashboardOptions = ref<{ label: string; value: string }[]>([]);

async function load() {
  try {
    const [p, d, st] = await Promise.all([getMe(), listDashboards({}), getSettings()]);
    sshScheme.value = st.ssh_uri_enabled ? st.ssh_uri_scheme : null;
    profile.value = p;
    Object.assign(form, {
      display_name: p.display_name,
      default_remote_user: p.default_remote_user,
      ssh_template: p.ssh_template,
      ...p.prefs,
    });
    defaultDashboard.value = p.default_dashboard_id;
    dashboardOptions.value = d.results.map((x) => ({ label: `${x.title} (${x.scope})`, value: x.id }));
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  }
}

async function save() {
  const p = profile.value;
  if (!p) return;
  saving.value = true;
  saveError.value = '';
  fieldErrors.value = {};
  try {
    await updateMe(p.version, { ...form, display_name: form.display_name.trim() });
    if (defaultDashboard.value !== p.default_dashboard_id) await setMyDefaultDashboard(defaultDashboard.value);
    // The top-bar toggles are per-browser; follow the saved profile.
    ui.setDensity(form.density);
    ui.setTheme(form.theme === 'DARK' ? 'dark' : 'light');
    $q.notify({ type: 'positive', message: 'Profile saved' });
    await Promise.all([load(), session.fetchBootstrap()]);
  } catch (e) {
    if (e instanceof ApiError) fieldErrors.value = e.fieldErrors;
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}

onMounted(load);
</script>
