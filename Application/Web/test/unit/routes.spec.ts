/**
 * `/` and `/dashboard` canonicalise to `/dashboard/<uuid>` using the caller's effective default dashboard
 * (UI_DESIGN.md §2), through the real session store (routes.ts's `toDefaultDashboard`).
 */
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryHistory, createRouter } from 'vue-router';
import { authGuard } from '@/router/guard';
import routes from '@/router/routes';
import { useSessionStore, type BootstrapResponse } from '@/stores/session';

function bootstrapPayload(overrides: Partial<BootstrapResponse> = {}): BootstrapResponse {
  return {
    instance: { name: 'PANIC', version: '0.6.0' },
    me: {
      id: 'usr-1',
      username: 'jdoe',
      display_name: 'J. Doe',
      auth_source: 'LOCAL',
      prefs: { density: 'COMFORT', theme: 'DARK', unreachable_policy: 'DIM' },
    },
    real_user: null,
    view_as: null,
    permissions: { global_admin: false, can_add_global: false, can_add_team: true, can_view_as: false },
    client: { ip: '198.51.100.23', zone: { id: 'zone-default', name: 'Default' }, zone_source: 'DEFAULT' },
    nav: { dashboards: [{ id: 'dash-xyz', title: 'Network Ops', icon: 'router', default: true, locked: true }] },
    default_dashboard: { id: 'dash-xyz', source: 'USER' },
    ...overrides,
  };
}

function stubFetch(payload: BootstrapResponse): void {
  vi.stubGlobal(
    'fetch',
    vi.fn((input: Request | string) => {
      const url = typeof input === 'string' ? input : input.url;
      if (url.includes('/api/v1/ui/bootstrap')) {
        return new Response(JSON.stringify(payload), { status: 200, headers: { 'Content-Type': 'application/json' } });
      }
      return new Response(null, { status: 404 });
    }),
  );
}

describe('/ and /dashboard default-dashboard redirect', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('redirects / to /dashboard/<uuid> of the effective default dashboard', async () => {
    stubFetch(bootstrapPayload());
    const session = useSessionStore();
    const router = createRouter({ history: createMemoryHistory(), routes });
    router.beforeEach((to) => authGuard(to, session));
    await router.push('/');
    expect(router.currentRoute.value.name).toBe('dashboard-view');
    expect(router.currentRoute.value.params.id).toBe('dash-xyz');
  });

  it('redirects /dashboard the same way', async () => {
    stubFetch(bootstrapPayload());
    const session = useSessionStore();
    const router = createRouter({ history: createMemoryHistory(), routes });
    router.beforeEach((to) => authGuard(to, session));
    await router.push('/dashboard');
    expect(router.currentRoute.value.name).toBe('dashboard-view');
    expect(router.currentRoute.value.params.id).toBe('dash-xyz');
  });

  it('falls back to /catalog when the caller has no default dashboard at all', async () => {
    stubFetch(bootstrapPayload({ default_dashboard: null, nav: { dashboards: [] } }));
    const session = useSessionStore();
    const router = createRouter({ history: createMemoryHistory(), routes });
    router.beforeEach((to) => authGuard(to, session));
    await router.push('/');
    expect(router.currentRoute.value.name).toBe('catalog');
  });
});
