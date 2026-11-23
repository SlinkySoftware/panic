<!--
  Protocol-aware catalog item modal: live preview (normalized key, hygiene, visible duplicate), server
  field errors, and a duplicate prompt that resends with force_allow_duplicate.
-->
<template>
  <q-dialog :model-value="modelValue" persistent @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 640px; max-width: 95vw">
      <q-form data-testid="catalog-item-form" @submit="save(false)">
        <q-card-section class="text-h6">{{ itemId ? 'Edit item' : 'Add item' }}</q-card-section>
        <q-card-section v-if="loadingItem" class="flex flex-center"><q-spinner size="lg" /></q-card-section>
        <q-card-section v-else class="row q-col-gutter-md">
          <q-input
            v-model="form.title"
            class="col-12"
            label="Title"
            v-bind="{ ...field, ...err('title') }"
            autofocus
            :rules="[required]"
          />

          <q-select
            v-model="form.protocol"
            class="col-12 col-sm-3"
            :options="protocolOptions"
            label="Protocol"
            v-bind="field"
            emit-value
            map-options
          />
          <q-input
            v-model="form.host"
            class="col-12 col-sm-6"
            :label="form.protocol === 'WEB' ? 'Host or URL' : 'Host'"
            v-bind="{ ...field, ...err('host') }"
            :rules="[required]"
          />
          <q-input
            v-model.number="form.port"
            class="col-12 col-sm-3"
            label="Port"
            type="number"
            v-bind="{ ...field, ...err('port') }"
          />

          <q-input
            v-if="form.protocol !== 'RDP'"
            v-model="form.path_or_args"
            class="col-12"
            :label="form.protocol === 'WEB' ? 'Path' : 'Arguments'"
            v-bind="{ ...field, ...err('path_or_args') }"
          />
          <q-input
            v-if="form.protocol !== 'WEB'"
            v-model="form.account_override"
            :class="form.protocol === 'LOCAL_APP' ? 'col-12 col-sm-6' : 'col-12'"
            label="Account override"
            placeholder="Blank = your default remote user"
            stack-label
            v-bind="{ ...field, ...err('account_override') }"
          />
          <q-input
            v-if="form.protocol === 'LOCAL_APP'"
            v-model="form.custom_uri"
            class="col-12 col-sm-6"
            label="Custom URI"
            v-bind="{ ...field, ...err('custom_uri') }"
          />

          <q-select
            v-model="form.site"
            class="col-12 col-sm-6"
            :options="sites"
            label="Site"
            v-bind="{ ...field, ...err('site') }"
          />
          <q-select
            v-model="form.scope"
            class="col-12 col-sm-6"
            :options="scopeOptions"
            label="Scope"
            v-bind="{ ...field, ...err('scope') }"
          />
          <q-select
            v-if="form.scope === 'TEAM'"
            v-model="form.team_ids"
            class="col-12"
            :options="teamOptions"
            label="Teams"
            v-bind="{ ...field, ...err('team_ids') }"
            multiple
            use-chips
            emit-value
            map-options
          />

          <q-select
            v-model="form.zone_ids"
            class="col-12"
            :options="zoneOptions"
            label="Zones (where this item is reachable)"
            v-bind="{ ...field, ...err('zone_ids') }"
            multiple
            use-chips
            emit-value
            map-options
          />
          <q-select
            v-model="form.tags"
            class="col-12"
            label="Tags"
            v-bind="field"
            multiple
            use-chips
            use-input
            new-value-mode="add-unique"
            hide-dropdown-icon
          />
          <q-input
            v-model="form.description"
            class="col-12"
            label="Description"
            v-bind="field"
            type="textarea"
            autogrow
          />

          <div v-if="preview" class="col-12">
            <q-banner dense rounded :class="preview.hygiene_passed ? 'bg-grey-2 text-grey-9' : 'bg-orange-2'">
              <div class="text-caption">Normalized target</div>
              <div class="text-body2" style="font-family: monospace">{{ preview.normalized_key }}</div>
              <div v-for="h in preview.hygiene_errors" :key="h" class="text-negative text-caption">{{ h }}</div>
              <div v-if="preview.duplicate && preview.duplicate.id !== itemId" class="text-warning text-caption">
                Duplicate of "{{ preview.duplicate.title }}"
              </div>
            </q-banner>
          </div>
          <div v-if="saveError" class="col-12">
            <q-banner class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat label="Cancel" />
          <q-btn type="submit" color="primary" label="Save" :loading="saving" :disable="loadingItem" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import {
  createCatalogItem,
  getCatalogItem,
  previewCatalogItem,
  PROTOCOLS,
  updateCatalogItem,
  type CatalogInput,
  type Preview,
  type Scope,
  type Zone,
} from '@/api/catalog';
import type { CodeNamed } from '@/api/admin';
import { ApiError } from '@/api/http';
import { useSessionStore } from '@/stores/session';

const props = defineProps<{
  modelValue: boolean;
  itemId: string | null;
  sites: string[];
  teams: CodeNamed[];
  zones: Zone[];
}>();
const emit = defineEmits<{ 'update:modelValue': [open: boolean]; saved: [] }>();

const $q = useQuasar();
const session = useSessionStore();

const protocolOptions = PROTOCOLS.map((p) => ({ label: p === 'LOCAL_APP' ? 'Local app' : p, value: p }));
const teamOptions = computed(() => props.teams.map((t) => ({ label: `${t.code} - ${t.name}`, value: t.id })));
const zoneOptions = computed(() => props.zones.map((z) => ({ label: z.name, value: z.id })));
const scopeOptions = computed<Scope[]>(() => {
  const p = session.permissions;
  const out: Scope[] = [];
  if (p?.global_admin || p?.can_add_global) out.push('GLOBAL');
  if (p?.global_admin || p?.can_add_team) out.push('TEAM');
  out.push('PERSONAL');
  return out;
});

const blank = (): CatalogInput => ({
  title: '',
  description: '',
  protocol: 'SSH',
  host: '',
  port: null,
  site: props.sites[0] ?? '',
  path_or_args: '',
  custom_uri: '',
  account_override: '',
  tags: [],
  scope: 'PERSONAL',
  team_ids: [],
  zone_ids: [],
});

const form = reactive<CatalogInput>(blank());
const loadingItem = ref(false);
const saving = ref(false);
const saveError = ref('');
const fieldErrors = ref<Record<string, string[]>>({});
const preview = ref<Preview | null>(null);

// Shared field look: errors take space only when present, so side-by-side fields keep one height.
const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const required = (v: string) => (!!v && String(v).trim().length > 0) || 'Required';
const err = (field: string) => {
  const msgs = fieldErrors.value[field];
  return msgs?.length ? { error: true, errorMessage: msgs.join(' ') } : {};
};

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return;
    saveError.value = '';
    fieldErrors.value = {};
    preview.value = null;
    Object.assign(form, blank());
    if (!props.itemId) return;
    loadingItem.value = true;
    try {
      const item = await getCatalogItem(props.itemId);
      Object.assign(form, {
        title: item.title,
        description: item.description,
        protocol: item.protocol,
        host: item.host,
        port: item.port,
        site: item.site,
        path_or_args: item.path_or_args,
        custom_uri: item.custom_uri,
        account_override: item.account_override,
        tags: [...item.tags],
        scope: item.scope,
        team_ids: [...item.team_ids],
        zone_ids: [...item.zone_ids],
      });
    } catch (e) {
      saveError.value = e instanceof Error ? e.message : String(e);
    } finally {
      loadingItem.value = false;
    }
  },
);

// Live preview, debounced: only once there is a host to normalize.
let previewTimer: ReturnType<typeof setTimeout> | undefined;
watch(
  () => [form.protocol, form.host, form.port, form.path_or_args, form.account_override, form.custom_uri, form.scope],
  () => {
    clearTimeout(previewTimer);
    if (!props.modelValue || !form.host.trim()) {
      preview.value = null;
      return;
    }
    previewTimer = setTimeout(() => {
      previewCatalogItem({
        protocol: form.protocol,
        host: form.host.trim(),
        port: form.port || null,
        path_or_args: form.path_or_args,
        account_override: form.account_override,
        custom_uri: form.custom_uri,
        scope: form.scope,
      })
        .then((p) => (preview.value = p))
        .catch(() => (preview.value = null));
    }, 400);
  },
);

async function save(force: boolean) {
  saving.value = true;
  saveError.value = '';
  fieldErrors.value = {};
  const body: CatalogInput = {
    ...form,
    title: form.title.trim(),
    host: form.host.trim(),
    port: form.port || null,
    team_ids: form.scope === 'TEAM' ? form.team_ids : [],
    ...(force ? { force_allow_duplicate: true } : {}),
  };
  try {
    if (props.itemId) await updateCatalogItem(props.itemId, body);
    else await createCatalogItem(body);
    $q.notify({ type: 'positive', message: `Saved ${body.title}` });
    emit('update:modelValue', false);
    emit('saved');
  } catch (e) {
    if (e instanceof ApiError && e.errorCode === 'DUPLICATE_CATALOG_ITEM') {
      const existing = (e.body?.existing_item as { title?: string } | undefined)?.title ?? 'an existing item';
      $q.dialog({
        title: 'Duplicate target',
        message: `This target is already in the catalog as "${existing}". Save anyway?`,
        cancel: true,
        ok: { label: 'Save anyway', color: 'warning' },
      }).onOk(() => void save(true));
      return;
    }
    if (e instanceof ApiError) fieldErrors.value = e.fieldErrors;
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    saving.value = false;
  }
}
</script>
