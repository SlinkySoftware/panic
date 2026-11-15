<!--
  HOST or LIST widget in the locked view. Missing (deleted / invisible) targets render as placeholders; a
  truncated LIST offers "Show all" linking to /lists?open=<id>. Unavailable (zone-restricted) items are hidden
  until the per-widget "Show Unavailable Items" checkbox is ticked; it only appears when there are some.
-->
<template>
  <q-card flat bordered class="column no-wrap full-height">
    <q-card-section class="q-py-xs q-px-sm text-subtitle2 ellipsis">{{ heading }}</q-card-section>
    <q-separator />
    <div class="col scroll">
      <template v-if="widget.widget_type === 'HOST'">
        <template v-if="hostItem">
          <ItemLauncher v-if="hostItem.reachable || showUnavailable" :item="hostItem" />
          <div v-else class="q-pa-sm text-grey-6 text-caption" data-testid="host-unavailable-hidden">
            Unavailable from your zone.
          </div>
        </template>
        <div v-else class="q-pa-sm text-grey-6 text-caption">Item unavailable (deleted or not visible).</div>
      </template>
      <template v-else>
        <q-list v-if="list" dense separator>
          <ItemLauncher v-for="item in shownItems" :key="item.id" :item="item" />
          <q-item v-if="shownItems.length === 0">
            <q-item-section class="text-grey-6">
              {{ listItems.length === 0 ? 'No items.' : 'All items are unavailable from your zone.' }}
            </q-item-section>
          </q-item>
        </q-list>
        <div v-else class="q-pa-sm text-grey-6 text-caption">List unavailable (deleted or not visible).</div>
      </template>
    </div>
    <q-card-actions v-if="unavailableCount > 0 || list?.truncated" class="q-py-none q-px-sm">
      <q-checkbox
        v-if="unavailableCount > 0"
        v-model="showUnavailable"
        dense
        size="sm"
        class="text-caption"
        :label="`Show Unavailable Items (${unavailableCount})`"
        data-testid="show-unavailable"
      />
      <q-space />
      <q-btn
        v-if="list?.truncated"
        flat
        dense
        size="sm"
        color="primary"
        :to="{ name: 'lists', query: { open: list.id } }"
      >
        Show all ({{ list.item_count }})
      </q-btn>
    </q-card-actions>
  </q-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import type { ItemView } from '@/api/catalog';
import type { Widget, WidgetList } from '@/api/dashboards';
import ItemLauncher from './ItemLauncher.vue';

const props = defineProps<{ widget: Widget; items: Record<string, ItemView>; lists: Record<string, WidgetList> }>();

const hostItem = computed(() => (props.widget.catalog_item_id ? props.items[props.widget.catalog_item_id] : undefined));
const list = computed(() => (props.widget.list_id ? props.lists[props.widget.list_id] : undefined));
const listItems = computed(() =>
  (list.value?.item_ids ?? []).map((id) => props.items[id]).filter((i): i is ItemView => !!i),
);
// Hidden by default; per widget, not remembered across reloads.
const showUnavailable = ref(false);
const shownItems = computed(() =>
  showUnavailable.value ? listItems.value : listItems.value.filter((i) => i.reachable),
);
const unavailableCount = computed(() =>
  props.widget.widget_type === 'HOST'
    ? hostItem.value && !hostItem.value.reachable
      ? 1
      : 0
    : listItems.value.filter((i) => !i.reachable).length,
);
const heading = computed(
  () => props.widget.title || (props.widget.widget_type === 'HOST' ? hostItem.value?.title : list.value?.title) || '—',
);
</script>
