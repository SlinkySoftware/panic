<!--
  Rendered for any AR-1.4 route that has no dedicated screen. The route exists and is reachable -- the
  explicit-URL requirement is about routing existing, not about every screen having its own page.
-->
<template>
  <q-page class="q-pa-lg">
    <div class="text-h5">{{ title }}</div>
    <q-banner class="q-mt-md bg-grey-3 text-grey-9" rounded dense>
      <template #avatar><q-icon name="construction" /></template>
      <div>{{ caption }}</div>
      <div v-if="task" class="text-caption q-mt-xs">Coming soon ({{ task }}).</div>
    </q-banner>
  </q-page>
</template>

<script setup lang="ts">
defineProps<{
  title: string;
  caption?: string;
  task?: string;
  icon?: string;
  id?: string | string[];
}>();
</script>
