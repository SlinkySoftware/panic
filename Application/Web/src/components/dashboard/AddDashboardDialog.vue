<!--
  Menu "Add dashboard": pin an existing visible dashboard (GLOBAL / TEAM / own PERSONAL) not yet in the menu,
  or create a new one (starts empty, pinned to the creator's menu). Either way, it then opens.
-->
<template>
  <q-dialog :model-value="modelValue" persistent @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 520px; max-width: 95vw">
      <q-form @submit="save">
        <q-card-section class="text-h6 q-pb-none">Add dashboard</q-card-section>
        <q-tabs v-model="tab" dense align="left" active-color="primary" indicator-color="primary" class="q-px-md">
          <q-tab name="existing" label="Add existing" />
          <q-tab name="new" label="Create new" />
        </q-tabs>
        <q-separator />
        <q-card-section v-if="tab === 'existing'" class="q-gutter-y-sm">
          <div class="row q-col-gutter-sm">
            <q-input
              v-model="search"
              class="col"
              placeholder="Search dashboards"
              debounce="300"
              clearable
              v-bind="field"
            >
              <template #prepend><q-icon name="search" /></template>
            </q-input>
            <q-select
              v-model="scopeFilter"
              class="col-4"
              :options="['GLOBAL', 'TEAM', 'PERSONAL']"
              label="Scope"
              clearable
              v-bind="field"
            />
          </div>
          <q-list bordered separator class="rounded-borders" style="max-height: 320px; overflow-y: auto">
            <q-item v-if="loadingList"
              ><q-item-section class="flex flex-center"><q-spinner /></q-item-section
            ></q-item>
            <q-item v-else-if="available.length === 0">
              <q-item-section class="text-grey-6"
                >No other dashboards available. Create a new one instead.</q-item-section
              >
            </q-item>
            <q-item v-for="d in available" :key="d.id" clickable @click="addExisting(d.id)">
              <q-item-section avatar><q-icon :name="d.icon || 'dashboard'" /></q-item-section>
              <q-item-section>{{ d.title }}</q-item-section>
              <q-item-section side><q-badge :color="scopeColor[d.scope]" :label="d.scope" /></q-item-section>
            </q-item>
          </q-list>
          <q-banner v-if="saveError" class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
        </q-card-section>
        <q-card-section v-else class="row q-col-gutter-md">
          <q-input v-model="form.title" class="col-12" label="Title" autofocus :rules="[required]" v-bind="field" />
          <q-select v-model="form.scope" class="col-12 col-sm-4" :options="scopeOptions" label="Scope" v-bind="field" />
          <q-select
            v-if="form.scope === 'TEAM'"
            v-model="form.team_ids"
            class="col-12 col-sm-8"
            :options="teamOptions"
            label="Teams"
            multiple
            use-chips
            emit-value
            map-options
            v-bind="field"
          />
          <div class="col-12 row items-center q-gutter-sm">
            <span class="text-body2 text-grey-8">Menu icon</span>
            <IconPicker v-model="form.icon" :label="form.icon.replace(/_/g, ' ')" />
          </div>
          <q-input
            v-model="form.description"
            class="col-12"
            label="Description"
            type="textarea"
            autogrow
            v-bind="field"
          />
          <q-checkbox v-model="form.set_as_user_default" class="col-12" label="Make this my default dashboard" />
          <div v-if="saveError" class="col-12">
            <q-banner class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat label="Cancel" />
          <q-btn v-if="tab === 'new'" type="submit" color="primary" label="Create" :loading="saving" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { listCodeNamed, type CodeNamed } from '@/api/admin';
import type { Scope } from '@/api/catalog';
import { createDashboard, listDashboards, pinDashboard, type DashboardSummary } from '@/api/dashboards';
import { useSessionStore } from '@/stores/session';
import IconPicker from './IconPicker.vue';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [open: boolean] }>();

const router = useRouter();
const session = useSessionStore();

const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const required = (v: string) => (!!v && v.trim().length > 0) || 'Required';

const teams = ref<CodeNamed[]>([]);
const teamOptions = computed(() => teams.value.map((t) => ({ label: `${t.code} - ${t.name}`, value: t.id })));
const scopeOptions = computed<Scope[]>(() => {
  const p = session.permissions;
  const out: Scope[] = [];
  if (p?.global_admin || p?.can_add_global) out.push('GLOBAL');
  if (p?.global_admin || p?.can_add_team) out.push('TEAM');
  out.push('PERSONAL');
  return out;
});

const form = reactive<{
  title: string;
  description: string;
  scope: Scope;
  team_ids: string[];
  set_as_user_default: boolean;
  icon: string;
}>({ title: '', description: '', scope: 'PERSONAL', team_ids: [], set_as_user_default: false, icon: 'dashboard' });
const saving = ref(false);
const saveError = ref('');

const scopeColor: Record<Scope, string> = { GLOBAL: 'primary', TEAM: 'teal', PERSONAL: 'grey-7' };
const tab = ref<'existing' | 'new'>('existing');
const search = ref('');
const scopeFilter = ref<Scope | null>(null);
const available = ref<DashboardSummary[]>([]);
const loadingList = ref(false);

async function loadAvailable() {
  loadingList.value = true;
  try {
    const res = await listDashboards({ q: search.value ?? '', scope: scopeFilter.value ?? undefined });
    available.value = res.results.filter((d) => !d.in_menu);
  } catch (e) {
    available.value = [];
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loadingList.value = false;
  }
}
watch([search, scopeFilter], loadAvailable);

async function addExisting(id: string) {
  saveError.value = '';
  try {
    await pinDashboard(id);
    await session.fetchBootstrap();
    emit('update:modelValue', false);
    await router.push({ name: 'dashboard-view', params: { id } });
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e);
  }
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return;
    Object.assign(form, {
      title: '',
      description: '',
      scope: 'PERSONAL',
      team_ids: [],
      set_as_user_default: false,
      icon: 'dashboard',
    });
    saveError.value = '';
    search.value = '';
    scopeFilter.value = null;
    void loadAvailable().then(() => {
      if (available.value.length === 0) tab.value = 'new';
    });
    tab.value = 'existing';
    teams.value = await listCodeNamed('teams').catch(() => []);
  },
);

async function save() {
  saving.value = true;
  saveError.value = '';
  try {
    const d = await createDashboard({
      ...form,
      title: form.title.trim(),
      team_ids: form.scope === 'TEAM' ? form.team_ids : [],
    });
    await session.fetchBootstrap(); // menu pins + default changed
    emit('update:modelValue', false);
    await router.push({ name: 'dashboard-view', params: { id: d.id } });
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}
</script>
