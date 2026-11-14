<template>
  <q-layout view="hHh lpR fFf">
    <q-page-container>
      <q-page class="flex flex-center">
        <q-card class="panic-login-card" bordered>
          <q-card-section class="row items-center q-gutter-sm">
            <q-icon name="shield" size="md" color="primary" />
            <div>
              <div class="text-h6">{{ instanceName }}</div>
              <div class="text-caption text-grey">Sign in to continue</div>
            </div>
          </q-card-section>

          <q-banner v-if="loadError" class="bg-negative text-white q-mx-md" rounded dense>
            <template #avatar><q-icon name="error" /></template>
            Could not reach the server. You can still try to sign in.
          </q-banner>

          <q-form v-if="showLocalForm" data-testid="login-form" @submit="onSubmit">
            <q-card-section class="q-gutter-md">
              <q-banner v-if="error" data-testid="login-error" class="bg-negative text-white" rounded dense>
                <template #avatar><q-icon name="error" /></template>
                {{ error }}
              </q-banner>
              <q-input
                v-model="username"
                label="Username"
                name="username"
                autocomplete="username"
                autofocus
                outlined
                :rules="[required]"
                lazy-rules
              />
              <q-input
                v-model="password"
                label="Password"
                name="password"
                :type="showPassword ? 'text' : 'password'"
                autocomplete="current-password"
                outlined
                :rules="[required]"
                lazy-rules
              >
                <template #append>
                  <q-icon
                    :name="showPassword ? 'visibility_off' : 'visibility'"
                    class="cursor-pointer"
                    :aria-label="showPassword ? 'Hide password' : 'Show password'"
                    @click="showPassword = !showPassword"
                  />
                </template>
              </q-input>
            </q-card-section>
            <q-card-actions align="right" class="q-px-md q-pb-md">
              <q-btn
                type="submit"
                color="primary"
                label="Sign in"
                :loading="submitting"
                unelevated
                data-testid="login-submit"
              />
            </q-card-actions>
          </q-form>

          <q-card-section v-if="showLocalForm && showOidc" class="text-center text-caption text-grey q-py-none">
            or
          </q-card-section>

          <q-card-section v-if="showOidc">
            <q-btn
              class="full-width"
              outline
              no-caps
              icon="login"
              :label="`Sign in with ${oidcProviderName}`"
              data-testid="login-oidc"
              @click="onOidc"
            />
          </q-card-section>

          <q-card-section v-if="!showLocalForm && !showOidc" class="text-caption text-grey">
            No sign-in method is configured for this instance.
          </q-card-section>
        </q-card>
      </q-page>
    </q-page-container>
  </q-layout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { fetchProviders, oidcLoginUrl, type ProvidersResponse } from '@/api/auth';
import { ApiError } from '@/api/http';
import { safeRedirect } from '@/router/guard';
import { useSessionStore } from '@/stores/session';

const session = useSessionStore();
const route = useRoute();
const router = useRouter();

const providers = ref<ProvidersResponse | null>(null);
const loadError = ref(false);
const instanceName = computed(() => providers.value?.instance_name ?? 'PANIC');
const showLocalForm = computed(
  () => providers.value == null || providers.value.local_enabled || providers.value.ldap_enabled,
);
const showOidc = computed(() => providers.value?.oidc.enabled === true);
const oidcProviderName = computed(() => providers.value?.oidc.provider_name ?? 'SSO');

const username = ref('');
const password = ref('');
const showPassword = ref(false);
const submitting = ref(false);
const error = ref('');

const required = (v: string) => (!!v && v.length > 0) || 'Required';

onMounted(async () => {
  try {
    providers.value = await fetchProviders();
  } catch {
    loadError.value = true;
  }
});

function nextTarget(): string {
  return safeRedirect(route.query.next);
}

async function onSubmit(): Promise<void> {
  error.value = '';
  submitting.value = true;
  try {
    await session.login({ username: username.value, password: password.value });
    password.value = '';
    await router.replace(nextTarget());
  } catch (e) {
    if (e instanceof ApiError) {
      error.value = e.status >= 500 || e.status === 0 ? `Server error: ${e.message}` : e.message;
      if (e.requestId && e.status >= 500) error.value += ` (request ${e.requestId})`;
    } else {
      error.value = e instanceof Error ? e.message : String(e);
    }
  } finally {
    submitting.value = false;
  }
}

function onOidc(): void {
  globalThis.location.href = oidcLoginUrl(nextTarget());
}
</script>
