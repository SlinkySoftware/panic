<!--
  Dashboard icon picker: a curated grid of Material icons (bundled with @quasar/extras material-icons) plus
  search, shown in the left menu next to the dashboard. Any valid Material icon name may also be typed.
-->
<template>
  <div class="row items-center q-gutter-sm">
    <q-btn outline no-caps :icon="modelValue" :label="label" @click="open = true">
      <q-tooltip>Change icon</q-tooltip>
    </q-btn>
    <q-dialog v-model="open">
      <q-card style="width: 520px; max-width: 95vw">
        <q-card-section class="text-h6 q-pb-sm">Choose an icon</q-card-section>
        <q-card-section class="q-pt-none">
          <q-input
            v-model="search"
            outlined
            dense
            autofocus
            clearable
            placeholder="Search, or type any Material icon name"
          >
            <template #prepend><q-icon name="search" /></template>
          </q-input>
        </q-card-section>
        <q-card-section class="q-pt-none" style="max-height: 50vh; overflow-y: auto">
          <div class="panic-icon-grid">
            <q-btn
              v-for="i in shown"
              :key="i"
              flat
              round
              :icon="i"
              :color="i === modelValue ? 'primary' : undefined"
              :class="{ 'panic-icon-selected': i === modelValue }"
              :aria-label="i"
              @click="choose(i)"
            >
              <q-tooltip>{{ i.replace(/_/g, ' ') }}</q-tooltip>
            </q-btn>
          </div>
          <div v-if="customName" class="q-mt-md row items-center q-gutter-sm">
            <q-btn outline no-caps :icon="customName" :label="`Use “${customName}”`" @click="choose(customName)" />
            <span class="text-caption text-grey-7">Blank icon = not a Material icon name.</span>
          </div>
        </q-card-section>
        <q-card-actions align="right"><q-btn v-close-popup flat label="Cancel" /></q-card-actions>
      </q-card>
    </q-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';

withDefaults(defineProps<{ modelValue: string; label?: string }>(), { label: 'Icon' });
const emit = defineEmits<{ 'update:modelValue': [icon: string] }>();

// Operations-flavoured Material icons; all exist in the bundled material-icons font.
const ICONS = [
  'dashboard',
  'space_dashboard',
  'grid_view',
  'view_quilt',
  'home',
  'star',
  'bookmark',
  'push_pin',
  'router',
  'dns',
  'storage',
  'lan',
  'hub',
  'cable',
  'wifi',
  'cell_tower',
  'satellite_alt',
  'settings_ethernet',
  'device_hub',
  'memory',
  'developer_board',
  'computer',
  'desktop_windows',
  'laptop',
  'terminal',
  'code',
  'cloud',
  'cloud_queue',
  'public',
  'language',
  'vpn_lock',
  'security',
  'shield',
  'lock',
  'vpn_key',
  'key',
  'admin_panel_settings',
  'policy',
  'gpp_good',
  'build',
  'construction',
  'handyman',
  'settings',
  'tune',
  'monitor_heart',
  'speed',
  'insights',
  'analytics',
  'query_stats',
  'bug_report',
  'warning',
  'notifications',
  'support_agent',
  'groups',
  'group',
  'person',
  'apartment',
  'business',
  'factory',
  'warehouse',
  'store',
  'location_on',
  'map',
  'travel_explore',
  'flight',
  'local_shipping',
  'bolt',
  'power',
  'electrical_services',
  'videocam',
  'print',
  'phone',
  'call',
  'mail',
  'science',
  'school',
  'local_hospital',
  'account_balance',
  'rocket_launch',
  'science',
  'apps',
  'widgets',
  'category',
  'label',
].filter((v, i, a) => a.indexOf(v) === i);

const VALID = /^[a-z0-9_]{1,40}$/;

const open = ref(false);
const search = ref('');

const term = computed(() => (search.value ?? '').trim().toLowerCase().replace(/\s+/g, '_'));
const shown = computed(() => (term.value ? ICONS.filter((i) => i.includes(term.value)) : ICONS));
const customName = computed(() => (VALID.test(term.value) && !ICONS.includes(term.value) ? term.value : ''));

function choose(icon: string) {
  emit('update:modelValue', icon);
  open.value = false;
  search.value = '';
}
</script>

<style scoped>
.panic-icon-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(44px, 1fr));
  gap: 4px;
}
.panic-icon-selected {
  outline: 2px solid currentColor;
}
</style>
