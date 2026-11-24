<!--
  Protocol-aware catalog item modal: one shared host, a checkbox row per protocol (SSH and RDP are mutually
  exclusive) with its own port and path / arguments / command, live preview (normalized keys, hygiene, visible
  duplicate), server field errors, and a duplicate prompt that resends with force_allow_duplicate.
  `copy` opens an existing item as a new one: it saves as a create, and only once something has changed.
-->
<template>
  <q-dialog :model-value="modelValue" persistent @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 880px; max-width: 95vw">
      <q-form data-testid="catalog-item-form" @submit="save(false)">
        <q-card-section class="text-h6">{{ heading }}</q-card-section>
        <q-card-section v-if="loadingItem" class="flex flex-center"><q-spinner size="lg" /></q-card-section>
        <q-card-section v-else class="panic-form-row">
          <div class="panic-form-fields row q-col-gutter-md">
            <q-input
              v-model="form.title"
              class="col-12"
              label="Title"
              v-bind="{ ...field, ...err('title') }"
              autofocus
              :rules="[required]"
            />

            <q-input
              v-model="form.host"
              class="col-12"
              :label="conns.URL.enabled ? 'Host or URL' : 'Host'"
              v-bind="{ ...field, ...err('host') }"
              :rules="[required]"
            />

            <div class="col-12" data-testid="catalog-protocols">
              <div class="text-caption text-grey-7 q-mb-xs">Protocols</div>
              <div v-for="p in PROTOCOLS" :key="p" class="row items-center q-col-gutter-sm q-mb-xs">
                <div class="col-12 col-sm-2">
                  <q-checkbox
                    v-model="conns[p].enabled"
                    dense
                    :label="PROTOCOL_LABELS[p]"
                    :disable="blocked(p)"
                    :data-testid="`protocol-${p}`"
                  >
                    <q-tooltip v-if="blocked(p)">An item may have SSH or RDP, not both</q-tooltip>
                  </q-checkbox>
                </div>
                <template v-if="conns[p].enabled">
                  <q-input
                    v-model.number="conns[p].port"
                    class="col-4 col-sm-2"
                    label="Port"
                    type="number"
                    :placeholder="DEFAULT_PORTS[p]"
                    stack-label
                    v-bind="field"
                  />
                  <q-input
                    v-if="p !== 'RDP'"
                    v-model="conns[p].path_or_args"
                    :class="p === 'SSH' ? 'col-8 col-sm-8' : 'col-8 col-sm-4'"
                    :label="PATH_LABELS[p]"
                    v-bind="field"
                  />
                  <q-input
                    v-if="p === 'URL' || p === 'LOCAL_APP'"
                    v-model="conns[p].custom_uri"
                    class="col-12 col-sm-4"
                    :label="p === 'URL' ? 'Full URL override' : 'Custom URI'"
                    v-bind="field"
                  />
                </template>
              </div>
              <div v-if="fieldErrors.connections?.length" class="text-negative text-caption">
                {{ fieldErrors.connections.join(' ') }}
              </div>
            </div>

            <q-input
              v-if="conns.SSH.enabled || conns.RDP.enabled || conns.LOCAL_APP.enabled"
              v-model="form.account_override"
              class="col-12"
              label="Account override"
              placeholder="Blank = your default remote user"
              stack-label
              v-bind="{ ...field, ...err('account_override') }"
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
                <div class="text-caption">Normalized targets</div>
                <div v-for="k in preview.normalized_keys" :key="k" class="text-body2" style="font-family: monospace">
                  {{ k }}
                </div>
                <div v-for="h in preview.hygiene_errors" :key="h" class="text-negative text-caption">{{ h }}</div>
                <div v-if="preview.duplicate && preview.duplicate.id !== itemId" class="text-warning text-caption">
                  Duplicate of "{{ preview.duplicate.title }}"
                </div>
              </q-banner>
            </div>
            <div v-if="saveError" class="col-12">
              <q-banner class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
            </div>
          </div>
          <div class="panic-form-actions">
            <q-btn type="submit" color="primary" label="Save" :loading="saving" :disable="loadingItem || unchangedCopy">
              <q-tooltip v-if="unchangedCopy">Change something before saving the copy</q-tooltip>
            </q-btn>
            <q-btn v-close-popup flat label="Cancel" />
          </div>
        </q-card-section>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import {
  createCatalogItem,
  EXCLUSIVE_PROTOCOLS,
  getCatalogItem,
  previewCatalogItem,
  PROTOCOL_LABELS,
  PROTOCOLS,
  updateCatalogItem,
  type CatalogInput,
  type Connection,
  type Preview,
  type Protocol,
  type Scope,
  type Zone,
} from '@/api/catalog';
import type { CodeNamed } from '@/api/admin';
import { ApiError } from '@/api/http';
import { useSessionStore } from '@/stores/session';

const props = withDefaults(
  defineProps<{
    modelValue: boolean;
    itemId: string | null;
    copy?: boolean;
    sites: string[];
    teams: CodeNamed[];
    zones: Zone[];
  }>(),
  { copy: false },
);
const emit = defineEmits<{ 'update:modelValue': [open: boolean]; saved: [] }>();

const $q = useQuasar();
const session = useSessionStore();

const DEFAULT_PORTS: Record<Protocol, string> = { SSH: '22', RDP: '3389', URL: '443', LOCAL_APP: '' };
const PATH_LABELS: Record<Protocol, string> = { SSH: 'Arguments', RDP: '', URL: 'Path', LOCAL_APP: 'Command' };

const heading = computed(() => (props.copy ? 'Copy item' : props.itemId ? 'Edit item' : 'Add item'));
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

type Fields = Omit<CatalogInput, 'connections' | 'force_allow_duplicate'>;
type ConnRow = Connection & { enabled: boolean };

const blank = (): Fields => ({
  title: '',
  description: '',
  host: '',
  site: props.sites[0] ?? '',
  account_override: '',
  tags: [],
  scope: 'PERSONAL',
  team_ids: [],
  zone_ids: [],
});
const blankConns = (): Record<Protocol, ConnRow> =>
  Object.fromEntries(
    PROTOCOLS.map((p) => [
      p,
      { protocol: p, enabled: p === 'SSH', port: null, path_or_args: '', custom_uri: '' } satisfies ConnRow,
    ]),
  ) as Record<Protocol, ConnRow>;

const form = reactive<Fields>(blank());
// Every protocol keeps its row while unchecked, so toggling one off and on again loses nothing.
const conns = reactive<Record<Protocol, ConnRow>>(blankConns());
const loadingItem = ref(false);
const saving = ref(false);
const saveError = ref('');
const fieldErrors = ref<Record<string, string[]>>({});
const preview = ref<Preview | null>(null);
// The copy as first loaded: Save stays disabled until the form differs from it.
const copySnapshot = ref('');

// Shared field look: errors take space only when present, so side-by-side fields keep one height.
const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const required = (v: string) => (!!v && String(v).trim().length > 0) || 'Required';
const err = (field: string) => {
  const msgs = fieldErrors.value[field];
  return msgs?.length ? { error: true, errorMessage: msgs.join(' ') } : {};
};

/** SSH and RDP exclude each other: one checked disables the other. */
const blocked = (p: Protocol) =>
  EXCLUSIVE_PROTOCOLS.includes(p) && EXCLUSIVE_PROTOCOLS.some((o) => o !== p && conns[o].enabled);

const connections = (): Connection[] =>
  PROTOCOLS.filter((p) => conns[p].enabled).map((p) => ({
    protocol: p,
    port: conns[p].port || null,
    path_or_args: p === 'RDP' ? '' : conns[p].path_or_args.trim(),
    custom_uri: p === 'URL' || p === 'LOCAL_APP' ? conns[p].custom_uri.trim() : '',
  }));

const body = (): CatalogInput => ({
  ...form,
  title: form.title.trim(),
  host: form.host.trim(),
  connections: connections(),
  team_ids: form.scope === 'TEAM' ? form.team_ids : [],
});

const unchangedCopy = computed(
  () => props.copy && !!copySnapshot.value && JSON.stringify(body()) === copySnapshot.value,
);

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return;
    saveError.value = '';
    fieldErrors.value = {};
    preview.value = null;
    copySnapshot.value = '';
    Object.assign(form, blank());
    Object.assign(conns, blankConns());
    if (!props.itemId) return;
    loadingItem.value = true;
    try {
      const item = await getCatalogItem(props.itemId);
      Object.assign(form, {
        title: item.title,
        description: item.description,
        host: item.host,
        site: item.site,
        account_override: item.account_override,
        tags: [...item.tags],
        scope: item.scope,
        team_ids: [...item.team_ids],
        zone_ids: [...item.zone_ids],
      });
      conns.SSH.enabled = false;
      for (const c of item.connections) Object.assign(conns[c.protocol], { ...c, enabled: true });
      if (props.copy) {
        // A copy is always a new item of a scope the caller may create.
        if (!scopeOptions.value.includes(form.scope)) Object.assign(form, { scope: 'PERSONAL', team_ids: [] });
        copySnapshot.value = JSON.stringify(body());
      }
    } catch (e) {
      saveError.value = e instanceof Error ? e.message : String(e);
    } finally {
      loadingItem.value = false;
    }
  },
);

// Live preview, debounced: only once there is a host and a protocol to normalize.
let previewTimer: ReturnType<typeof setTimeout> | undefined;
watch(
  () => [form.host, form.account_override, form.scope, JSON.stringify(connections())],
  () => {
    clearTimeout(previewTimer);
    const conn = connections();
    if (!props.modelValue || !form.host.trim() || conn.length === 0) {
      preview.value = null;
      return;
    }
    previewTimer = setTimeout(() => {
      previewCatalogItem({
        host: form.host.trim(),
        connections: conn,
        account_override: form.account_override,
        scope: form.scope,
        ...(props.itemId && !props.copy ? { item_id: props.itemId } : {}),
      })
        .then((p) => (preview.value = p))
        .catch(() => (preview.value = null));
    }, 400);
  },
);

async function save(force: boolean) {
  if (connections().length === 0) {
    fieldErrors.value = { connections: ['Select at least one protocol.'] };
    return;
  }
  saving.value = true;
  saveError.value = '';
  fieldErrors.value = {};
  const data: CatalogInput = { ...body(), ...(force ? { force_allow_duplicate: true } : {}) };
  try {
    if (props.itemId && !props.copy) await updateCatalogItem(props.itemId, data);
    else await createCatalogItem(data);
    $q.notify({ type: 'positive', message: `Saved ${data.title}` });
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
