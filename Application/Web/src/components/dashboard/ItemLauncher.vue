<!-- One launchable item: click to launch; unreachable items are dimmed with the reason on hover. -->
<template>
  <q-item clickable dense :class="{ 'panic-unreachable': !item.reachable }" @click="launch(item)">
    <q-item-section avatar>
      <q-icon :name="icons[item.protocol] ?? 'link'" :color="item.reachable ? 'primary' : 'grey-6'" />
    </q-item-section>
    <q-item-section>
      <q-item-label lines="1">{{ item.title }}</q-item-label>
      <q-item-label caption lines="1">{{ item.target }}</q-item-label>
    </q-item-section>
    <q-item-section side>
      <div class="row no-wrap items-center">
        <q-badge v-if="item.site" outline color="grey-7" :label="item.site" class="q-mr-xs" />
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
            item.protocol === 'SSH' ? 'Open in SSH client (set up on your Profile)' : 'Open with system handler'
          }}</q-tooltip>
        </q-btn>
      </div>
    </q-item-section>
    <q-tooltip v-if="!item.reachable && item.unreachable_reason">{{ item.unreachable_reason }}</q-tooltip>
  </q-item>
</template>

<script setup lang="ts">
import type { ItemView } from '@/api/catalog';
import { useLaunch } from '@/composables/useLaunch';

defineProps<{ item: ItemView }>();
const { launch, openUri } = useLaunch();

const icons: Record<string, string> = { SSH: 'terminal', RDP: 'desktop_windows', WEB: 'language', LOCAL_APP: 'apps' };
</script>

<style scoped>
.panic-unreachable {
  opacity: 0.5;
}
</style>
