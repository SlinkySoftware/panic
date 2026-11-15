/** Smoke test for the session store (API.md §4.1/§4.2), mocking `fetch` directly (no network, no Server). */
import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { resetCsrfToken } from '@/api/http';
import { useSessionStore, type BootstrapResponse } from '@/stores/session';

function bootstrap(overrides: Partial<BootstrapResponse> = {}): BootstrapResponse {
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
    permissions: { global_admin: true, can_add_global: true, can_add_team: true, can_view_as: true },
    client: { ip: '198.51.100.23', zone: { id: 'zone-1', name: 'Jump Hosts' }, zone_source: 'CIDR' },
    nav: { dashboards: [{ id: 'dash-1', title: 'Network Ops', icon: 'router', default: true, locked: true }] },
    default_dashboard: { id: 'dash-1', source: 'USER' },
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('session store', () => {
  let calls: { method: string; url: string }[];

  beforeEach(() => {
    setActivePinia(createPinia());
    resetCsrfToken();
    calls = [];
    document.cookie = 'panic_csrftoken=test-token; path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = 'panic_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });

  it('starts unauthenticated and loads the bootstrap payload once per page load', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request) => {
        calls.push({ method: input.method, url: input.url });
        return jsonResponse(bootstrap());
      }),
    );
    const session = useSessionStore();
    expect(session.isAuthenticated).toBe(false);

    const [a, b] = await Promise.all([session.ensureLoaded(), session.ensureLoaded()]);
    expect(a).toEqual(b);
    expect(calls.filter((c) => c.url.includes('/ui/bootstrap'))).toHaveLength(1); // deduped concurrent calls

    expect(session.isAuthenticated).toBe(true);
    expect(session.isAdmin).toBe(true);
    expect(session.navDashboards).toEqual([
      { id: 'dash-1', title: 'Network Ops', icon: 'router', default: true, locked: true },
    ]);
    expect(session.defaultDashboard).toEqual({ id: 'dash-1', source: 'USER' });
    expect(session.zone).toEqual({ id: 'zone-1', name: 'Jump Hosts' });

    await session.ensureLoaded();
    expect(calls.filter((c) => c.url.includes('/ui/bootstrap'))).toHaveLength(1); // cached, no second call
  });

  it('resolves to "not signed in" on a 401, without throwing', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse({ error_code: 'UNAUTHENTICATED', detail: 'no' }, 401)),
    );
    const session = useSessionStore();
    await expect(session.ensureLoaded()).resolves.toBeNull();
    expect(session.isAuthenticated).toBe(false);
  });

  it('login() calls the auth endpoint then refreshes bootstrap', async () => {
    let loggedIn = false;
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request) => {
        const url = new URL(input.url).pathname;
        if (url.endsWith('/auth/csrf')) return new Response(null, { status: 204 });
        if (url.endsWith('/auth/login')) {
          loggedIn = true;
          return jsonResponse({ me: bootstrap().me });
        }
        if (url.endsWith('/ui/bootstrap')) return jsonResponse(bootstrap({ me: loggedIn ? bootstrap().me : null }));
        return new Response(null, { status: 404 });
      }),
    );
    const session = useSessionStore();
    await session.login({ username: 'jdoe', password: 'secret' });
    expect(session.isAuthenticated).toBe(true);
    expect(session.me?.username).toBe('jdoe');
  });

  it('logout() clears the session locally even if it ran after a successful call', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request) => {
        const url = new URL(input.url).pathname;
        if (url.endsWith('/auth/logout')) return new Response(null, { status: 204 });
        return jsonResponse(bootstrap());
      }),
    );
    const session = useSessionStore();
    await session.ensureLoaded();
    expect(session.isAuthenticated).toBe(true);
    await session.logout();
    expect(session.isAuthenticated).toBe(false);
  });

  it('startViewAs()/exitViewAs() replace the bootstrap payload with the response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((input: Request) => {
        const url = new URL(input.url).pathname;
        if (url.endsWith('/admin/view-as') && input.method === 'PUT') {
          return jsonResponse(bootstrap({ view_as: { id: 'usr-2', username: 'alice', display_name: 'Alice' } }));
        }
        if (url.endsWith('/admin/view-as') && input.method === 'DELETE') {
          return jsonResponse(bootstrap({ view_as: null }));
        }
        return jsonResponse(bootstrap());
      }),
    );
    const session = useSessionStore();
    await session.ensureLoaded();
    await session.startViewAs('usr-2');
    expect(session.isViewingAs).toBe(true);
    expect(session.viewAs?.username).toBe('alice');
    await session.exitViewAs();
    expect(session.isViewingAs).toBe(false);
  });

  it('clear() forgets the session locally without calling Server', async () => {
    const fetchMock = vi.fn(() => jsonResponse(bootstrap()));
    vi.stubGlobal('fetch', fetchMock);
    const session = useSessionStore();
    await session.ensureLoaded();
    const callsBefore = fetchMock.mock.calls.length;
    session.clear();
    expect(session.isAuthenticated).toBe(false);
    expect(fetchMock.mock.calls.length).toBe(callsBefore);
  });
});
