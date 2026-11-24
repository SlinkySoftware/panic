<!--
  Edit List modal: the only place items are reordered (drag, or the arrow buttons). The picker offers
  only visible items of the list's own scope. Saves the full ordered item_ids with If-Match; a stale save shows
  the conflict banner. Read-only ("Show all") when the caller cannot edit.
-->
<template>
  <q-dialog :model-value="modelValue" persistent @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 720px; max-width: 95vw">
      <q-form @submit="save">
        <q-card-section class="text-h6">{{
          !listId ? 'New list' : readOnly ? form.title : 'Edit list'
        }}</q-card-section>
        <q-card-section v-if="loading" class="flex flex-center"><q-spinner size="lg" /></q-card-section>
        <q-card-section v-else class="row q-col-gutter-md">
          <template v-if="!readOnly">
            <q-input
              v-model="form.title"
              class="col-12"
              label="Title"
              v-bind="{ ...field, ...err('title') }"
              autofocus
              :rules="[required]"
            />
            <q-select
              v-model="form.scope"
              class="col-12 col-sm-4"
              :options="scopeOptions"
              label="Scope"
              :disable="!!listId && items.length > 0"
              v-bind="{ ...field, ...err('scope') }"
            >
              <q-tooltip v-if="!!listId && items.length > 0">Remove all items to change scope</q-tooltip>
            </q-select>
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
              v-bind="{ ...field, ...err('team_ids') }"
            />
            <q-input
              v-model="form.description"
              class="col-12"
              label="Description"
              type="textarea"
              autogrow
              v-bind="field"
            />

            <q-select
              :model-value="null"
              class="col-12"
              label="Add item"
              :options="pickerOptions"
              option-label="title"
              use-input
              input-debounce="300"
              v-bind="field"
              @filter="searchItems"
              @update:model-value="addItem"
            >
              <template #option="scope">
                <q-item v-bind="scope.itemProps">
                  <q-item-section>
                    <q-item-label>{{ scope.opt.title }}</q-item-label>
                    <q-item-label caption
                      >{{ protocolsLabel(scope.opt.protocols) }} · {{ scope.opt.target }}</q-item-label
                    >
                  </q-item-section>
                </q-item>
              </template>
              <template #no-option
                ><q-item><q-item-section class="text-grey">No matching items</q-item-section></q-item></template
              >
            </q-select>
          </template>
          <div v-else-if="form.description" class="col-12 text-body2">{{ form.description }}</div>

          <div class="col-12">
            <q-list bordered separator class="rounded-borders">
              <q-item v-if="items.length === 0"
                ><q-item-section class="text-grey">No items yet.</q-item-section></q-item
              >
              <q-item
                v-for="(item, i) in items"
                :key="item.id"
                dense
                :draggable="!readOnly"
                :class="{ 'bg-blue-1': dragOver === i }"
                @dragstart="dragFrom = i"
                @dragover.prevent="dragOver = i"
                @dragleave="dragOver = null"
                @drop.prevent="drop(i)"
              >
                <q-item-section v-if="!readOnly" avatar
                  ><q-icon name="drag_indicator" class="cursor-move"
                /></q-item-section>
                <q-item-section>
                  <q-item-label>{{ item.title }}</q-item-label>
                  <q-item-label caption>{{ protocolsLabel(item.protocols) }} · {{ item.target }}</q-item-label>
                </q-item-section>
                <q-item-section v-if="!readOnly" side class="row no-wrap">
                  <div>
                    <q-btn
                      flat
                      round
                      dense
                      size="sm"
                      icon="arrow_upward"
                      :disable="i === 0"
                      aria-label="Move up"
                      @click="move(i, i - 1)"
                    />
                    <q-btn
                      flat
                      round
                      dense
                      size="sm"
                      icon="arrow_downward"
                      :disable="i === items.length - 1"
                      aria-label="Move down"
                      @click="move(i, i + 1)"
                    />
                    <q-btn flat round dense size="sm" icon="close" aria-label="Remove" @click="items.splice(i, 1)" />
                  </div>
                </q-item-section>
              </q-item>
            </q-list>
          </div>

          <div v-if="conflict" class="col-12">
            <q-banner class="bg-warning" rounded dense>
              This list was changed by someone else since you opened it.
              <template #action><q-btn flat label="Reload" @click="load" /></template>
            </q-banner>
          </div>
          <div v-else-if="saveError" class="col-12">
            <q-banner class="bg-negative text-white" rounded dense>{{ saveError }}</q-banner>
          </div>
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat :label="readOnly ? 'Close' : 'Cancel'" />
          <q-btn v-if="!readOnly" type="submit" color="primary" label="Save" :loading="saving" :disable="loading" />
        </q-card-actions>
      </q-form>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { useQuasar } from 'quasar';
import type { CodeNamed } from '@/api/admin';
import { listCatalog, protocolsLabel, type ItemView, type Scope } from '@/api/catalog';
import { ApiError } from '@/api/http';
import { createList, getList, replaceList } from '@/api/lists';
import { useSessionStore } from '@/stores/session';

const props = defineProps<{ modelValue: boolean; listId: string | null; teams: CodeNamed[] }>();
const emit = defineEmits<{ 'update:modelValue': [open: boolean]; saved: [] }>();

const $q = useQuasar();
const session = useSessionStore();

const field = { outlined: true, dense: true, hideBottomSpace: true } as const;
const required = (v: string) => (!!v && v.trim().length > 0) || 'Required';

const teamOptions = computed(() => props.teams.map((t) => ({ label: `${t.code} - ${t.name}`, value: t.id })));
const scopeOptions = computed<Scope[]>(() => {
  const p = session.permissions;
  const out: Scope[] = [];
  if (p?.global_admin || p?.can_add_global) out.push('GLOBAL');
  if (p?.global_admin || p?.can_add_team) out.push('TEAM');
  out.push('PERSONAL');
  return out;
});

const form = reactive<{ title: string; description: string; scope: Scope; team_ids: string[] }>({
  title: '',
  description: '',
  scope: 'PERSONAL',
  team_ids: [],
});
const items = ref<ItemView[]>([]);
const version = ref(0);
const readOnly = ref(false);
const loading = ref(false);
const saving = ref(false);
const saveError = ref('');
const conflict = ref(false);
const fieldErrors = ref<Record<string, string[]>>({});
const err = (f: string) => {
  const m = fieldErrors.value[f];
  return m?.length ? { error: true, errorMessage: m.join(' ') } : {};
};

async function load() {
  saveError.value = '';
  conflict.value = false;
  fieldErrors.value = {};
  readOnly.value = false;
  Object.assign(form, { title: '', description: '', scope: 'PERSONAL', team_ids: [] });
  items.value = [];
  version.value = 0;
  if (!props.listId) return;
  loading.value = true;
  try {
    const l = await getList(props.listId);
    Object.assign(form, { title: l.title, description: l.description, scope: l.scope, team_ids: [...l.team_ids] });
    items.value = [...l.items];
    version.value = l.version;
    readOnly.value = !l.can_edit;
  } catch (e) {
    saveError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) void load();
  },
);

// ---- item picker: same-scope, visible items only (the server enforces this too)
const pickerOptions = ref<ItemView[]>([]);
function searchItems(val: string, update: (fn: () => void) => void) {
  const group = form.scope === 'PERSONAL' ? 'personal' : 'shared';
  listCatalog({ group, q: val, page: 1, page_size: 25 })
    .then((res) => {
      const have = new Set(items.value.map((i) => i.id));
      update(() => (pickerOptions.value = res.results.filter((r) => r.scope === form.scope && !have.has(r.id))));
    })
    .catch(() => update(() => (pickerOptions.value = [])));
}
function addItem(item: ItemView | null) {
  if (item && !items.value.some((i) => i.id === item.id)) items.value.push(item);
}

// ---- reorder
const dragFrom = ref<number | null>(null);
const dragOver = ref<number | null>(null);
function move(from: number, to: number) {
  const [it] = items.value.splice(from, 1);
  if (it) items.value.splice(to, 0, it);
}
function drop(to: number) {
  if (dragFrom.value !== null && dragFrom.value !== to) move(dragFrom.value, to);
  dragFrom.value = null;
  dragOver.value = null;
}

async function save() {
  saving.value = true;
  saveError.value = '';
  conflict.value = false;
  fieldErrors.value = {};
  const body = {
    title: form.title.trim(),
    description: form.description.trim(),
    scope: form.scope,
    team_ids: form.scope === 'TEAM' ? form.team_ids : [],
    item_ids: items.value.map((i) => i.id),
  };
  try {
    if (props.listId) await replaceList(props.listId, version.value, body);
    else await createList(body);
    $q.notify({ type: 'positive', message: `Saved ${body.title}` });
    emit('update:modelValue', false);
    emit('saved');
  } catch (e) {
    if (e instanceof ApiError && e.errorCode === 'VERSION_CONFLICT') conflict.value = true;
    else {
      if (e instanceof ApiError) fieldErrors.value = e.fieldErrors;
      saveError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    saving.value = false;
  }
}
</script>
