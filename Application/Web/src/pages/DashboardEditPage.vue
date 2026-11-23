<!--
  /dashboard/<id>/edit: 12-column grid editor. Drag a widget by its header to move it, drag the
  corner to resize; whatever it lands on is pushed down. Add Widget, widget Properties, dashboard details,
  Save (PUT layout with If-Match; a stale save shows the conflict banner), Cancel.
-->
<template>
  <q-page class="q-pa-md">
    <div v-if="loading" class="flex flex-center q-pa-xl"><q-spinner size="xl" /></div>
    <q-banner v-else-if="loadError" class="bg-negative text-white" rounded>{{ loadError }}</q-banner>
    <template v-else-if="dash">
      <div class="row items-center q-mb-md q-gutter-x-sm">
        <div class="text-h5">{{ dash.title }}</div>
        <q-badge color="orange-8" label="Editing" />
        <q-btn flat round dense icon="settings" aria-label="Dashboard details" @click="detailsOpen = true">
          <q-tooltip>Dashboard details</q-tooltip>
        </q-btn>
        <q-space />
        <q-btn outline color="primary" icon="add" label="Add widget" @click="addOpen = true" />
        <q-btn flat label="Cancel" @click="leave" />
        <q-btn color="primary" icon="save" label="Save" :loading="saving" :disable="!dirty" @click="save(false)" />
      </div>

      <q-banner v-if="conflict" class="bg-warning q-mb-md" rounded>
        Someone else changed this dashboard since you started editing.
        <template #action>
          <q-btn flat label="Discard mine and reload" @click="load" />
          <q-btn flat label="Overwrite theirs" @click="save(true)" />
        </template>
      </q-banner>
      <q-banner v-else-if="saveError" class="bg-negative text-white q-mb-md" rounded>{{ saveError }}</q-banner>

      <div ref="gridEl" class="panic-edit-grid" :style="{ gridTemplateRows: `repeat(${rowCount}, ${ROW_PX}px)` }">
        <div
          v-for="w in widgets"
          :key="w.id"
          class="panic-edit-widget"
          :class="{ 'panic-active': active?.id === w.id }"
          :style="{ gridColumn: `${w.grid_x} / span ${w.grid_w}`, gridRow: `${w.grid_y} / span ${w.grid_h}` }"
        >
          <q-card flat bordered class="full-height column no-wrap">
            <div class="row items-center no-wrap q-px-sm panic-drag" @pointerdown="startDrag($event, w, 'move')">
              <q-icon name="drag_indicator" class="q-mr-xs" />
              <div class="col ellipsis text-subtitle2">{{ label(w) }}</div>
              <q-btn
                flat
                round
                dense
                size="sm"
                icon="tune"
                aria-label="Properties"
                @pointerdown.stop
                @click="openProps(w)"
              />
              <q-btn flat round dense size="sm" icon="close" aria-label="Remove" @pointerdown.stop @click="remove(w)" />
            </div>
            <q-separator />
            <div class="col q-pa-sm text-caption text-grey-7">
              {{ w.widget_type }} · {{ w.grid_w }}×{{ w.grid_h }}
              <div v-if="missing(w)" class="text-negative">Unavailable: deleted or not visible</div>
            </div>
          </q-card>
          <div class="panic-resize" aria-label="Resize" @pointerdown.stop="startDrag($event, w, 'resize')" />
        </div>
        <div v-if="widgets.length === 0" class="panic-empty text-grey-6">No widgets. Use <b>Add widget</b>.</div>
      </div>
    </template>

    <AddWidgetDialog v-model="addOpen" :exclude="onDashboard" @pick="addWidget" />

    <q-dialog v-model="propsOpen">
      <q-card v-if="editingWidget" style="width: 420px; max-width: 95vw">
        <q-card-section class="text-h6">Widget properties</q-card-section>
        <q-card-section class="row q-col-gutter-md">
          <q-input
            v-model="editingWidget.title"
            class="col-12"
            label="Title"
            :placeholder="defaultTitle(editingWidget)"
            stack-label
            v-bind="field"
          />
          <q-input
            v-model.number="editingWidget.grid_w"
            class="col-6"
            type="number"
            label="Width (3-12)"
            v-bind="field"
          />
          <q-input
            v-model.number="editingWidget.grid_h"
            class="col-6"
            type="number"
            label="Height (1-6)"
            v-bind="field"
          />
        </q-card-section>
        <q-card-actions align="right">
          <q-btn v-close-popup flat label="Cancel" />
          <q-btn color="primary" label="Apply" @click="applyProps" />
        </q-card-actions>
      </q-card>
    </q-dialog>

    <q-dialog v-model="detailsOpen">
      <q-card v-if="dash" style="width: 480px; max-width: 95vw">
        <q-card-section class="text-h6">Dashboard details</q-card-section>
        <q-card-section class="row q-col-gutter-md">
          <q-input v-model="details.title" class="col-12" label="Title" v-bind="field" />
          <div class="col-12 row items-center q-gutter-sm">
            <span class="text-body2 text-grey-8">Menu icon</span>
            <IconPicker v-model="details.icon" :label="details.icon.replace(/_/g, ' ')" />
          </div>
          <q-input
            v-model="details.description"
            class="col-12"
            label="Description"
            type="textarea"
            autogrow
            v-bind="field"
          />
          <q-checkbox
            v-if="session.isAdmin"
            v-model="details.always_display"
            class="col-12"
            label="Always shown in everyone's menu"
          />
        </q-card-section>
        <q-card-actions>
          <q-btn flat color="negative" icon="delete" label="Delete dashboard" @click="confirmDelete" />
          <q-space />
          <q-btn v-close-popup flat label="Cancel" />
          <q-btn color="primary" label="Save details" @click="saveDetails" />
        </q-card-actions>
      </q-card>
    </q-dialog>
  </q-page>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { onBeforeRouteLeave, useRouter } from 'vue-router';
import { useQuasar } from 'quasar';
import AddWidgetDialog, { type Picked } from '@/components/dashboard/AddWidgetDialog.vue';
import IconPicker from '@/components/dashboard/IconPicker.vue';
import { clampBox, COLS, nextFreeRow, settle } from '@/components/dashboard/grid';
import {
  deleteDashboard,
  getDashboard,
  getDashboardView,
  patchDashboard,
  putLayout,
  type DashboardResource,
  type DashboardView,
  type Widget,
} from '@/api/dashboards';
import { ApiError } from '@/api/http';
import { useSessionStore } from '@/stores/session';

const props = defineProps<{ id: string }>();

const $q = useQuasar();
const router = useRouter();
const session = useSessionStore();

const ROW_PX = 120;
const GAP_PX = 12;
const field = { outlined: true, dense: true, hideBottomSpace: true } as const;

const dash = ref<DashboardResource | null>(null);
const view = ref<DashboardView | null>(null);
const widgets = ref<Widget[]>([]);
const titles = ref<Record<string, string>>({}); // widget id -> picked title, for widgets added this session
const loading = ref(false);
const loadError = ref('');
const saving = ref(false);
const saveError = ref('');
const conflict = ref(false);
const dirty = ref(false);
const latestVersion = ref<number | null>(null);

const rowCount = computed(() => Math.max(nextFreeRow(widgets.value) + 1, 4));

async function load() {
  loading.value = true;
  loadError.value = '';
  conflict.value = false;
  saveError.value = '';
  try {
    const [d, v] = await Promise.all([getDashboard(props.id), getDashboardView(props.id)]);
    if (!d.can_edit) {
      await router.replace({ name: 'dashboard-view', params: { id: props.id } });
      return;
    }
    dash.value = d;
    view.value = v;
    widgets.value = d.widgets.map((w) => ({ ...w }));
    dirty.value = false;
  } catch (e) {
    loadError.value = e instanceof Error ? e.message : String(e);
  } finally {
    loading.value = false;
  }
}
watch(() => props.id, load, { immediate: true });

function defaultTitle(w: Widget): string {
  if (titles.value[w.id]) return titles.value[w.id] ?? '';
  if (w.widget_type === 'HOST' && w.catalog_item_id) return view.value?.items[w.catalog_item_id]?.title ?? 'Host';
  if (w.list_id) return view.value?.lists[w.list_id]?.title ?? 'List';
  return '';
}
const label = (w: Widget) => w.title || defaultTitle(w);
const missing = (w: Widget) =>
  !titles.value[w.id] &&
  ((w.catalog_item_id && view.value?.unavailable.items.includes(w.catalog_item_id)) ||
    (w.list_id && view.value?.unavailable.lists.includes(w.list_id)));

function commit(next: Widget[], movedId: string) {
  widgets.value = settle(
    next.map((w) => (w.id === movedId ? clampBox(w) : w)),
    movedId,
  );
  dirty.value = true;
}

// ---- drag to move / resize (pointer events; cell size derived from the grid's rendered width)
const gridEl = ref<HTMLElement | null>(null);
const active = ref<Widget | null>(null);
function startDrag(ev: PointerEvent, w: Widget, mode: 'move' | 'resize') {
  if (ev.button !== 0 || !gridEl.value) return;
  ev.preventDefault();
  const rect = gridEl.value.getBoundingClientRect();
  const colPx = (rect.width - GAP_PX * (COLS - 1)) / COLS + GAP_PX;
  const rowPx = ROW_PX + GAP_PX;
  const start = { x: ev.clientX, y: ev.clientY, w: { ...w } };
  active.value = w;
  const onMove = (e: PointerEvent) => {
    const dc = Math.round((e.clientX - start.x) / colPx);
    const dr = Math.round((e.clientY - start.y) / rowPx);
    const moved =
      mode === 'move'
        ? { ...start.w, grid_x: start.w.grid_x + dc, grid_y: start.w.grid_y + dr }
        : { ...start.w, grid_w: start.w.grid_w + dc, grid_h: start.w.grid_h + dr };
    const others = widgets.value.filter((o) => o.id !== w.id);
    commit([...others, moved], w.id);
  };
  const onUp = () => {
    active.value = null;
    window.removeEventListener('pointermove', onMove);
    window.removeEventListener('pointerup', onUp);
  };
  window.addEventListener('pointermove', onMove);
  window.addEventListener('pointerup', onUp);
}

// ---- add / properties / remove
const addOpen = ref(false);
const onDashboard = computed(
  () => new Set(widgets.value.map((w) => w.catalog_item_id ?? w.list_id).filter((id): id is string => !!id)),
);
function addWidget(p: Picked) {
  if (onDashboard.value.has(p.id)) {
    $q.notify({ type: 'warning', message: `"${p.title}" is already on this dashboard` });
    return;
  }
  const id = `w-${crypto.getRandomValues(new Uint32Array(2)).join('')}`;
  titles.value[id] = p.title;
  const w: Widget =
    p.type === 'HOST'
      ? {
          id,
          widget_type: 'HOST',
          title: '',
          grid_x: 1,
          grid_y: nextFreeRow(widgets.value),
          grid_w: 4,
          grid_h: 1,
          catalog_item_id: p.id,
        }
      : {
          id,
          widget_type: 'LIST',
          title: '',
          grid_x: 1,
          grid_y: nextFreeRow(widgets.value),
          grid_w: 6,
          grid_h: 3,
          list_id: p.id,
        };
  commit([...widgets.value, w], id);
}

const propsOpen = ref(false);
const editingWidget = ref<Widget | null>(null);
function openProps(w: Widget) {
  editingWidget.value = { ...w };
  propsOpen.value = true;
}
function applyProps() {
  const e = editingWidget.value;
  if (!e) return;
  commit(
    widgets.value.map((w) => (w.id === e.id ? { ...e, title: e.title.trim() } : w)),
    e.id,
  );
  propsOpen.value = false;
}
function remove(w: Widget) {
  widgets.value = widgets.value.filter((o) => o.id !== w.id);
  dirty.value = true;
}

// ---- save / cancel
async function save(overwrite: boolean) {
  if (!dash.value) return;
  saving.value = true;
  saveError.value = '';
  const version = overwrite && latestVersion.value !== null ? latestVersion.value : dash.value.version;
  try {
    const d = await putLayout(dash.value.id, version, widgets.value);
    dash.value = d;
    dirty.value = false;
    conflict.value = false;
    $q.notify({ type: 'positive', message: 'Dashboard saved' });
    await router.push({ name: 'dashboard-view', params: { id: d.id } });
  } catch (e) {
    if (e instanceof ApiError && e.errorCode === 'VERSION_CONFLICT') {
      conflict.value = true;
      latestVersion.value = Number(e.body?.current_version ?? dash.value.version);
    } else {
      saveError.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    saving.value = false;
  }
}

function leave() {
  void router.push({ name: 'dashboard-view', params: { id: props.id } });
}

onBeforeRouteLeave(
  () =>
    !dirty.value ||
    new Promise<boolean>((resolve) => {
      $q.dialog({ title: 'Discard changes?', message: 'Your layout changes are not saved.', cancel: true })
        .onOk(() => resolve(true))
        .onCancel(() => resolve(false));
    }),
);

// ---- dashboard details (PATCH) and delete
const detailsOpen = ref(false);
const details = reactive({ title: '', description: '', always_display: false, icon: 'dashboard' });
watch(detailsOpen, (open) => {
  if (open && dash.value)
    Object.assign(details, {
      title: dash.value.title,
      description: dash.value.description,
      always_display: dash.value.always_display,
      icon: dash.value.icon || 'dashboard',
    });
});
async function saveDetails() {
  if (!dash.value) return;
  try {
    const d = await patchDashboard(dash.value.id, dash.value.version, {
      title: details.title.trim(),
      description: details.description.trim(),
      icon: details.icon,
      ...(session.isAdmin ? { always_display: details.always_display } : {}),
    });
    Object.assign(dash.value, {
      title: d.title,
      description: d.description,
      always_display: d.always_display,
      icon: d.icon,
      version: d.version,
    });
    detailsOpen.value = false;
    await session.fetchBootstrap();
  } catch (e) {
    $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) });
  }
}
function confirmDelete() {
  const d = dash.value;
  if (!d) return;
  $q.dialog({
    title: 'Delete dashboard',
    message: `Delete "${d.title}" for everyone who can see it?`,
    cancel: true,
    ok: { label: 'Delete', color: 'negative' },
  }).onOk(() => {
    void deleteDashboard(d.id, d.version)
      .then(async () => {
        dirty.value = false;
        detailsOpen.value = false;
        await session.fetchBootstrap();
        await router.push({ name: 'root' });
      })
      .catch((e: unknown) => $q.notify({ type: 'negative', message: e instanceof Error ? e.message : String(e) }));
  });
}
</script>

<style scoped>
.panic-edit-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(12, minmax(0, 1fr));
  gap: 12px;
  padding: 8px;
  border-radius: 6px;
  background-image: linear-gradient(to right, rgba(128, 128, 128, 0.12) 1px, transparent 1px);
  background-size: calc((100% - 16px + 12px) / 12) 100%;
  background-position: 8px 0;
  user-select: none;
}
.panic-edit-widget {
  position: relative;
  min-width: 0;
}
.panic-active {
  opacity: 0.85;
  z-index: 2;
}
.panic-drag {
  cursor: move;
  min-height: 32px;
  touch-action: none;
}
.panic-resize {
  position: absolute;
  right: 2px;
  bottom: 2px;
  width: 14px;
  height: 14px;
  cursor: nwse-resize;
  border-right: 3px solid currentColor;
  border-bottom: 3px solid currentColor;
  opacity: 0.4;
  touch-action: none;
}
.panic-empty {
  grid-column: 1 / -1;
  grid-row: 1;
  align-self: center;
  text-align: center;
}
</style>
