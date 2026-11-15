<!--
  View As (Global Admins): pick a user, a zone, or both. No user = yourself; no zone = your real zone.
  While active, everything is read-only (the server refuses mutations).
-->
<template>
  <q-dialog :model-value="modelValue" @update:model-value="emit('update:modelValue', $event)">
    <q-card style="width: 460px; max-width: 95vw">
      <q-card-section class="text-h6">View As</q-card-section>
      <q-card-section class="q-gutter-y-md">
        <q-select
          v-model="userId"
          :options="userOptions"
          label="User"
          hint="Leave blank to view as yourself"
          use-input
          input-debounce="300"
          clearable
          emit-value
          map-options
          outlined
          dense
          data-testid="view-as-user"
          @filter="searchUsers"
        />
        <q-select
          v-model="zoneId"
          :options="zoneOptions"
          label="Zone"
          hint="Leave blank to use your real zone"
          clearable
          emit-value
          map-options
          outlined
          dense
          data-testid="view-as-zone"
        />
        <q-banner v-if="error" class="bg-negative text-white" rounded dense>{{ error }}</q-banner>
      </q-card-section>
      <q-card-actions align="right">
        <q-btn v-close-popup flat label="Cancel" />
        <q-btn color="primary" label="Start" :disable="!userId && !zoneId" :loading="starting" @click="start" />
      </q-card-actions>
    </q-card>
  </q-dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue';
import { useRouter } from 'vue-router';
import { listZonesAdmin } from '@/api/admin';
import { listUsers } from '@/api/users';
import { useSessionStore } from '@/stores/session';

const props = defineProps<{ modelValue: boolean }>();
const emit = defineEmits<{ 'update:modelValue': [open: boolean] }>();

const router = useRouter();
const session = useSessionStore();

const userId = ref<string | null>(null);
const zoneId = ref<string | null>(null);
const userOptions = ref<{ label: string; value: string }[]>([]);
const zoneOptions = ref<{ label: string; value: string }[]>([]);
const starting = ref(false);
const error = ref('');

function searchUsers(val: string, update: (fn: () => void) => void) {
  listUsers({ q: val, disabled: 'false', page: 1, page_size: 25 })
    .then((res) =>
      update(
        () =>
          (userOptions.value = res.results
            .filter((u) => u.id !== session.realUser?.id && u.id !== session.me?.id)
            .map((u) => ({ label: `${u.display_name} (${u.username})`, value: u.id }))),
      ),
    )
    .catch(() => update(() => (userOptions.value = [])));
}

watch(
  () => props.modelValue,
  async (open) => {
    if (!open) return;
    userId.value = null;
    zoneId.value = null;
    error.value = '';
    try {
      zoneOptions.value = (await listZonesAdmin()).map((z) => ({ label: z.name, value: z.id }));
    } catch {
      zoneOptions.value = [];
    }
  },
);

async function start() {
  starting.value = true;
  error.value = '';
  try {
    await session.startViewAs({ userId: userId.value, zoneId: zoneId.value });
    emit('update:modelValue', false);
    await router.push({ name: 'root' });
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e);
  } finally {
    starting.value = false;
  }
}
</script>
