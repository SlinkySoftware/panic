<!--
  SSH command template with presets (Profile). Picking a preset fills the template; editing it by hand makes
  the preset "Custom". Nothing extra is stored: the active preset is derived by comparing the template with
  the list. A preview shows the command for a sample host. The server re-validates (no password flags).
-->
<template>
  <div class="row q-col-gutter-md">
    <q-select
      :model-value="preset"
      class="col-12 col-sm-5"
      :options="options"
      label="SSH client"
      emit-value
      map-options
      outlined
      dense
      hide-bottom-space
      data-testid="ssh-preset"
      @update:model-value="pick"
    />
    <q-input
      :model-value="modelValue"
      class="col-12 col-sm-7"
      label="SSH command template"
      hint="Placeholders: {user} {host} {port} {flags}"
      input-style="font-family: monospace"
      outlined
      dense
      :error="!!error"
      :error-message="error"
      data-testid="ssh-template"
      @update:model-value="emit('update:modelValue', String($event ?? ''))"
    />
    <div class="col-12 text-caption text-grey-7">
      Example: <span class="mono" data-testid="ssh-preview">{{ preview }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue';
import { CUSTOM, SSH_PRESETS, presetFor, previewSsh } from './sshPresets';

const props = defineProps<{ modelValue: string; error?: string | undefined }>();
const emit = defineEmits<{ 'update:modelValue': [template: string] }>();

const options = [...SSH_PRESETS.map((p) => ({ label: p.label, value: p.id })), { label: 'Custom', value: CUSTOM }];
const preset = computed(() => presetFor(props.modelValue));
const preview = computed(() => previewSsh(props.modelValue));

function pick(id: string) {
  const p = SSH_PRESETS.find((x) => x.id === id);
  if (p) emit('update:modelValue', p.template); // "Custom" keeps whatever is in the field
}
</script>
