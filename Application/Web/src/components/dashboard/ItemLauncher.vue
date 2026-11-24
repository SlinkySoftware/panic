<!--
  One launchable item: click to launch its primary protocol; each other protocol (e.g. the URL of an SSH device)
  gets its own icon button on the right. Unreachable items (zone restrictions) are not launchable at all:
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
      <q-icon :name="PROTOCOL_ICONS[item.protocol] ?? 'link'" :color="item.reachable ? 'primary' : 'grey-6'" />
    </q-item-section>
    <q-item-section>
      <q-item-label lines="1">{{ item.title }}</q-item-label>
      <q-item-label caption lines="1">{{ item.target }}</q-item-label>
    </q-item-section>
    <!-- Fixed-width columns so rows line up whatever each contains (zones / site / action). -->
    <q-item-section v-if="showZones" side class="panic-col-zones" data-testid="item-zones">
      <div class="row no-wrap items-center justify-end q-gutter-x-xs full-width">
        <q-badge v-if="item.zone_names.length === 0" class="panic-badge" outline color="grey-6" label="All zones" />
        <template v-else>
          <q-badge
            v-for="z in item.zone_names.slice(0, 2)"
            :key="z"
            class="panic-badge panic-zone-badge"
            outline
            color="teal"
            :label="z"
          >
            <q-tooltip>{{ z }}</q-tooltip>
          </q-badge>
          <q-badge
            v-if="item.zone_names.length > 2"
            class="panic-badge"
            outline
            color="teal"
            :label="`+${item.zone_names.length - 2}`"
          >
            <q-tooltip>{{ item.zone_names.join(', ') }}</q-tooltip>
          </q-badge>
        </template>
      </div>
    </q-item-section>
    <q-item-section side class="panic-col-site">
      <q-badge v-if="item.site" class="panic-badge" outline color="grey-7" :label="item.site" />
    </q-item-section>
    <q-item-section side class="panic-col-action">
      <q-badge
        v-if="!item.reachable"
        class="panic-badge panic-unavailable"
        outline
        color="negative"
        label="Unavailable"
      />
      <div v-else class="row no-wrap items-center">
        <q-btn
          v-for="alt in item.alt_launches ?? []"
          :key="alt.protocol"
          flat
          round
          dense
          size="sm"
          :icon="PROTOCOL_ICONS[alt.protocol] ?? 'link'"
          :aria-label="altLabel(alt)"
          data-testid="item-alt-launch"
          @click.stop="launch(item, alt)"
        >
          <q-tooltip>{{ altLabel(alt) }}</q-tooltip>
        </q-btn>
        <q-btn
          v-if="item.launch?.uri"
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
      </div>
    </q-item-section>
    <q-tooltip v-if="!item.reachable && item.unreachable_reason">{{ item.unreachable_reason }}</q-tooltip>
  </q-item>
</template>

<script setup lang="ts">
import { PROTOCOL_ICONS, type AltLaunch, type ItemView, type Launch } from '@/api/catalog';
import { useLaunch } from '@/composables/useLaunch';

withDefaults(defineProps<{ item: ItemView; showZones?: boolean }>(), { showZones: false });
const { launch, openUri } = useLaunch();

const altVerb: Record<Launch['kind'], string> = { OPEN: 'Open', COPY: 'Copy command for', DOWNLOAD: 'Download' };
const altLabel = (l: AltLaunch) =>
  `${altVerb[l.kind]} ${l.protocol === 'LOCAL_APP' ? 'local app' : l.protocol} (${l.kind === 'OPEN' && l.url ? l.url : l.target})`;
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
  align-items: flex-end;
  overflow: hidden;
}
/* One badge look for the whole row (zones, All zones, site, Unavailable): same radius, padding, height. */
.panic-badge {
  border-radius: 4px;
  padding: 2px 6px;
  font-size: 11px;
  line-height: 14px;
  min-height: 0;
}
.panic-zone-badge {
  display: inline-block;
  max-width: 48%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.panic-col-site {
  width: 76px;
  align-items: center;
}
.panic-col-action {
  min-width: 92px;
  align-items: flex-end;
}
.panic-unavailable {
  font-weight: 600;
  border-width: 1.5px;
}
</style>
