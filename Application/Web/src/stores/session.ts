/**
 * Session state: the whole `GET /api/v1/ui/bootstrap` payload (API.md §4.2), not just a `me` object.
 *
 * `ensureLoaded()` asks Server once per page load; the router guard awaits it before every protected route.
 * `fetchBootstrap()` is also called again after sign-in and after any View As change (API.md §4.2: "Called once
 * per page load (and after sign-in / View As changes)"). `login()`/`logout()`/`startViewAs()`/`exitViewAs()` go
 * through the auth / admin endpoints and then refresh the bootstrap payload.
 */
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import * as authApi from '@/api/auth';
import type { LoginRequest } from '@/api/auth';
import { type components } from '@/api/client';
import { ApiError, requestJson } from '@/api/http';

export type BootstrapResponse = components['schemas']['BootstrapResponse'];
export type NavDashboard = components['schemas']['NavDashboard'];

export const useSessionStore = defineStore('session', () => {
  const bootstrap = ref<BootstrapResponse | null>(null);
  const loaded = ref(false);
  let inFlight: Promise<BootstrapResponse | null> | null = null;

  const isAuthenticated = computed(() => bootstrap.value?.me != null);
  const me = computed(() => bootstrap.value?.me ?? null);
  const realUser = computed(() => bootstrap.value?.real_user ?? null);
  const instance = computed(() => bootstrap.value?.instance ?? null);
  const permissions = computed(() => bootstrap.value?.permissions ?? null);
  const isAdmin = computed(() => permissions.value?.global_admin === true);
  const canViewAs = computed(() => permissions.value?.can_view_as === true);
  const viewAs = computed(() => bootstrap.value?.view_as ?? null);
  const isViewingAs = computed(() => viewAs.value !== null);
  const client = computed(() => bootstrap.value?.client ?? null);
  const zone = computed(() => client.value?.zone ?? null);
  const zoneSource = computed(() => client.value?.zone_source ?? null);
  const navDashboards = computed<NavDashboard[]>(() => bootstrap.value?.nav.dashboards ?? []);
  const defaultDashboard = computed(() => bootstrap.value?.default_dashboard ?? null);

  /** Re-read the session from Server. A `401` (anonymous) resolves to "not signed in"; other errors propagate. */
  async function fetchBootstrap(): Promise<BootstrapResponse | null> {
    inFlight ??= (async () => {
      try {
        const data = await requestJson<BootstrapResponse>('GET', '/ui/bootstrap');
        bootstrap.value = data;
        return data;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) {
          bootstrap.value = null;
          return null;
        }
        throw e;
      } finally {
        loaded.value = true;
      }
    })();
    try {
      return await inFlight;
    } finally {
      inFlight = null;
    }
  }

  /** Resolve the session once per page load; later calls reuse the result until `clear()`/a refresh. */
  async function ensureLoaded(): Promise<BootstrapResponse | null> {
    return loaded.value ? bootstrap.value : fetchBootstrap();
  }

  async function login(credentials: LoginRequest): Promise<void> {
    await authApi.login(credentials);
    await fetchBootstrap();
  }

  async function logout(): Promise<void> {
    try {
      await authApi.logout();
    } finally {
      clear();
    }
  }

  /** `PUT /api/v1/admin/view-as` (admin only, real user): switch perspective, then refresh bootstrap. */
  /** `PUT /api/v1/admin/view-as`: a user, a zone, or both (no user = yourself; no zone = your real zone). */
  async function startViewAs(target: { userId?: string | null; zoneId?: string | null }): Promise<void> {
    const data = await requestJson<BootstrapResponse>('PUT', '/admin/view-as', {
      user_id: target.userId ?? null,
      zone_id: target.zoneId ?? null,
    });
    bootstrap.value = data;
  }

  /** `DELETE /api/v1/admin/view-as`: the only mutation allowed while View As is active. */
  async function exitViewAs(): Promise<void> {
    const data = await requestJson<BootstrapResponse>('DELETE', '/admin/view-as');
    bootstrap.value = data;
  }

  /** Forget the session locally (logged out, or expired). Does not call Server. */
  function clear(): void {
    bootstrap.value = null;
    loaded.value = true;
  }

  return {
    bootstrap,
    loaded,
    isAuthenticated,
    me,
    realUser,
    instance,
    permissions,
    isAdmin,
    canViewAs,
    viewAs,
    isViewingAs,
    client,
    zone,
    zoneSource,
    navDashboards,
    defaultDashboard,
    fetchBootstrap,
    ensureLoaded,
    login,
    logout,
    startViewAs,
    exitViewAs,
    clear,
  };
});
