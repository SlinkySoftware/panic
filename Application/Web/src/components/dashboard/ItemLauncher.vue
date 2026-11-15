<!--
  One launchable item: click to launch. Unreachable items (zone restrictions) are not launchable at all:
  dimmed, a red "Unavailable" badge with the reason on hover, no launch icon, and clicking does nothing.
  `showZones` adds a column of badges for the zones the item is reachable from ("All zones" when unrestricted).
-->
<template>
  <q-item
    :clickable="item.reachable"
    dense
    :class="{ 'panic-unreachable': !item.reachable }"
    :data-testid="item.reachable ? 'item-launch' : 'item-unavailable'"
    @click="item.reachable && launch(item)"
  >
    <q-item-section avatar>
      <q-icon :name="icons[item.protocol] ?? 'link'" :color="item.reachable ? 'primary' : 'grey-6'" />
    </q-item-section>
    <q-item-section>
      <q-item-label lines="1">{{ item.title }}</q-item-label>
      <q-item-label caption lines="1">{{ item.target }}</q-item-label>
    </q-item-section>
    <!-- Fixed-width columns so rows line up whatever each contains (zones / site / action). -->
    <q-item-section v-if="showZones" side class="panic-col-zones" data-testid="item-zones">
      <div class="row no-wrap items-center q-gutter-x-xs full-width">
        <q-badge v-if="item.zone_names.length === 0" outline color="grey-6" label="All zones" />
        <template v-else>
          <q-badge
            v-for="z in item.zone_names.slice(0, 2)"
            :key="z"
            outline
            color="teal"
            class="panic-zone-badge"
            :label="z"
          >
            <q-tooltip>{{ z }}</q-tooltip>
          </q-badge>
          <q-badge v-if="item.zone_names.length > 2" outline color="teal" :label="`+${item.zone_names.length - 2}`">
            <q-tooltip>{{ item.zone_names.join(', ') }}</q-tooltip>
          </q-badge>
        </template>
      </div>
    </q-item-section>
    <q-item-section side class="panic-col-site">
      <q-badge v-if="item.site" outline color="grey-7" :label="item.site" />
    </q-item-section>
    <q-item-section side class="panic-col-action">
      <q-badge v-if="!item.reachable" outline color="negative" label="Unavailable" class="panic-unavailable" />
      <q-btn
        v-else-if="item.launch?.uri"
        flat
        round
        dense
        size="sm"
        icon="open_in_new"
        :aria-label="item.protocol === 'SSH' ? 'Open in SSH client' : 'Open with system handler'"
        @click.stop="openUri(item)"
      >
        <q-tooltip>{{
          item.protocol === 'SSH' ? 'Open in SSH client (set up in User Settings)' : 'Open with system handler'
        }}</q-tooltip>
      </q-btn>
    </q-item-section>
    <q-tooltip v-if="!item.reachable && item.unreachable_reason">{{ item.unreachable_reason }}</q-tooltip>
  </q-item>
</template>

<script setup lang="ts">
import type { ItemView } from '@/api/catalog';
import { useLaunch } from '@/composables/useLaunch';

withDefaults(defineProps<{ item: ItemView; showZones?: boolean }>(), { showZones: false });
const { launch, openUri } = useLaunch();

const icons: Record<string, string> = { SSH: 'terminal', RDP: 'desktop_windows', WEB: 'language', LOCAL_APP: 'apps' };
</script>

<style scoped>
.panic-unreachable {
  cursor: not-allowed;
}
.panic-unreachable :deep(.q-item__section--main),
.panic-unreachable :deep(.q-item__section--avatar) {
  opacity: 0.5;
}
.panic-col-zones {
  width: 36%;
  min-width: 0;
  align-items: flex-start;
  overflow: hidden;
}
.panic-zone-badge {
  max-width: 48%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  display: inline-block;
}
.panic-col-site {
  width: 76px;
  align-items: center;
}
.panic-col-action {
  width: 92px;
  align-items: flex-end;
}
.panic-unavailable {
  font-weight: 600;
  border-width: 1.5px;
}
</style>
