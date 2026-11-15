<!--
  HOST or LIST widget in the locked view. Missing (deleted / invisible) targets render as placeholders; a
  truncated LIST offers "Show all" linking to /lists?open=<id>.
-->
<template>
  <q-card flat bordered class="column no-wrap full-height">
    <q-card-section class="q-py-xs q-px-sm text-subtitle2 ellipsis">{{ heading }}</q-card-section>
    <q-separator />
    <div class="col scroll">
      <template v-if="widget.widget_type === 'HOST'">
        <ItemLauncher v-if="hostItem" :item="hostItem" />
        <div v-else class="q-pa-sm text-grey-6 text-caption">Item unavailable (deleted or not visible).</div>
      </template>
      <template v-else>
        <q-list v-if="list" dense separator>
          <ItemLauncher v-for="item in listItems" :key="item.id" :item="item" />
          <q-item v-if="listItems.length === 0"><q-item-section class="text-grey-6">No items.</q-item-section></q-item>
        </q-list>
        <div v-else class="q-pa-sm text-grey-6 text-caption">List unavailable (deleted or not visible).</div>
      </template>
    </div>
    <q-card-actions v-if="list?.truncated" align="right" class="q-py-none">
      <q-btn flat dense size="sm" color="primary" :to="{ name: 'lists', query: { open: list.id } }">
        Show all ({{ list.item_count }})
      </q-btn>
    </q-card-actions>
  </q-card>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import type { ItemView } from '@/api/catalog';
import type { Widget, WidgetList } from '@/api/dashboards';
import ItemLauncher from './ItemLauncher.vue';

const props = defineProps<{ widget: Widget; items: Record<string, ItemView>; lists: Record<string, WidgetList> }>();

const hostItem = computed(() => (props.widget.catalog_item_id ? props.items[props.widget.catalog_item_id] : undefined));
const list = computed(() => (props.widget.list_id ? props.lists[props.widget.list_id] : undefined));
const listItems = computed(() =>
  (list.value?.item_ids ?? []).map((id) => props.items[id]).filter((i): i is ItemView => !!i),
);
const heading = computed(
  () => props.widget.title || (props.widget.widget_type === 'HOST' ? hostItem.value?.title : list.value?.title) || '—',
);
</script>
