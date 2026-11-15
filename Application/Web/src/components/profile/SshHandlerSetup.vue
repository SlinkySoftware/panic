<!--
  Profile: per-user SSH URI handler setup (Windows). Generates a one-line PowerShell setup command for the
  chosen client and the matching remove command. No admin rights: everything goes under HKCU and
  %LOCALAPPDATA%\PANIC. Shown only when an admin has the handler enabled (Settings).
-->
<template>
  <q-card flat bordered>
    <q-card-section class="text-subtitle1 q-pb-none">Open SSH with one click (Windows)</q-card-section>
    <q-card-section class="q-gutter-y-md">
      <div class="text-body2 text-grey-8">
        Set this up once per Windows account. Afterwards the
        <q-icon name="open_in_new" size="16px" /> button on SSH items opens the session directly in your SSH client,
        instead of copying a command. No administrator rights are needed: it only writes to your own user profile.
      </div>

      <q-select
        v-model="client"
        :options="HANDLER_CLIENTS"
        label="SSH client to open"
        emit-value
        map-options
        outlined
        dense
        style="max-width: 360px"
        data-testid="handler-client"
      />

      <div>
        <div class="text-subtitle2">1. Install</div>
        <div class="text-caption text-grey-7 q-mb-xs">
          Open <b>Windows PowerShell</b> (Start → type "PowerShell", no need to run as administrator), paste this line
          and press Enter:
        </div>
        <CommandBox :command="setup" data-testid="handler-setup" />
      </div>

      <div>
        <div class="text-subtitle2">2. Try it</div>
        <div class="text-caption text-grey-7">
          Click <q-icon name="open_in_new" size="16px" /> on any SSH item. Your browser asks once whether to open "PANIC
          SSH": tick <i>Always allow</i>. For example, the link <span class="mono">{{ example.uri }}</span> runs
          <span class="mono">{{ example.runs }}</span>.
        </div>
      </div>

      <q-expansion-item dense dense-toggle icon="help_outline" label="Examples, troubleshooting and removal">
        <div class="q-pa-sm q-gutter-y-sm text-body2">
          <div>
            <b>PuTTY</b>: needs <span class="mono">putty.exe</span> on your PATH (installed PuTTY usually is). The
            handler runs <span class="mono">putty.exe -ssh user@host -P port</span>.
          </div>
          <div>
            <b>OpenSSH</b>: uses Windows' built-in <span class="mono">ssh.exe</span> and opens a console window. It runs
            <span class="mono">ssh.exe -p port user@host</span>.
          </div>
          <div>
            <b>Switching client</b>: pick the other client above and run its install line again; it replaces the
            previous one.
          </div>
          <div>
            <b>Nothing happens?</b> Your organisation may block PowerShell scripts or set a script policy that overrides
            "Bypass". Ask your desktop team, or keep using the copy button. Links that are not exactly
            <span class="mono">{{ scheme }}://user@host:port</span> are ignored by design.
          </div>
          <div class="text-subtitle2 q-mt-md">Remove</div>
          <CommandBox :command="remove" data-testid="handler-remove" />
        </div>
      </q-expansion-item>
    </q-card-section>
  </q-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import CommandBox from './CommandBox.vue';
import { HANDLER_CLIENTS, handlerExample, removeCommand, setupCommand, type HandlerClient } from './sshHandler';

const props = defineProps<{ scheme: string; preferredClient?: HandlerClient }>();

const client = ref<HandlerClient>(props.preferredClient ?? 'putty');
const setup = computed(() => setupCommand(client.value, props.scheme));
const remove = computed(() => removeCommand(props.scheme));
const example = computed(() => handlerExample(client.value, props.scheme));
</script>
