import { createPinia, setActivePinia } from 'pinia';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createMemoryHistory, createRouter, type Router } from 'vue-router';
import { authGuard, loginLocation, safeRedirect, type SessionState } from '@/router/guard';
import routes from '@/router/routes';

function fakeSession(overrides: Partial<SessionState> = {}): SessionState {
  return {
    isAuthenticated: false,
    isAdmin: false,
    ensureLoaded: () => Promise.resolve(undefined),
    ...overrides,
  };
}

function makeRouter(session: SessionState): Router {
  const router = createRouter({ history: createMemoryHistory(), routes });
  router.beforeEach((to) => authGuard(to, session));
  return router;
}

describe('safeRedirect', () => {
  it.each([
    ['/catalog', '/catalog'],
    ['/dashboard/abc?x=1#y', '/dashboard/abc?x=1#y'],
    [['/sites', '/x'], '/sites'],
    ['//evil.example/x', '/'],
    ['https://evil.example/', '/'],
    ['/\\evil.example', '/'],
    ['/login', '/'],
    ['/login?next=/x', '/'],
    [undefined, '/'],
    [42, '/'],
  ])('%j -> %s', (input, expected) => {
    expect(safeRedirect(input)).toBe(expected);
  });
});

describe('loginLocation', () => {
  it('uses `next` as the query param name', () => {
    expect(loginLocation('/catalog')).toEqual({ name: 'login', query: { next: '/catalog' } });
  });

  it('omits the query entirely when the target is just /', () => {
    expect(loginLocation('/')).toEqual({ name: 'login' });
  });
});

describe('authGuard', () => {
  // A redirect to `/` (the AR-2.5 admin-gate target) always cascades through `/`'s own `beforeEnter`
  // (`toDefaultDashboard`, routes.ts), which uses the real Pinia-backed session store regardless of the fake
  // `SessionState` handed to `authGuard` itself -- so every test below needs a real (anonymous) session too.
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.resolve(new Response(null, { status: 401 }))),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends anonymous users to /login with next= back to where they were going', async () => {
    const router = makeRouter(fakeSession());
    await router.push('/catalog?x=1');
    expect(router.currentRoute.value.name).toBe('login');
    expect(router.currentRoute.value.query.next).toBe('/catalog?x=1');
  });

  it('lets anonymous users see /login and the 404 page', async () => {
    const router = makeRouter(fakeSession());
    await router.push('/login');
    expect(router.currentRoute.value.name).toBe('login');
    await router.push('/no/such/page');
    expect(router.currentRoute.value.name).toBe('not-found');
  });

  it('lets a signed-in user through, and bounces them off /login to `next` (or /)', async () => {
    const router = makeRouter(fakeSession({ isAuthenticated: true }));
    await router.push('/catalog');
    expect(router.currentRoute.value.name).toBe('catalog');
    await router.push('/login?next=/sites');
    expect(router.currentRoute.value.name).toBe('sites');
  });

  it('sends anonymous users to /login when the session check itself fails (network/5xx)', async () => {
    const session = fakeSession({ ensureLoaded: () => Promise.reject(new Error('down')) });
    const router = makeRouter(session);
    await router.push('/settings');
    expect(router.currentRoute.value.name).toBe('login');
    expect(router.currentRoute.value.query.next).toBe('/settings');
  });

  it.each(['/settings/users', '/settings/orphans', '/settings/client-ip', '/audit'])(
    // authGuard redirects to `/`, which immediately cascades onward via its own `beforeEnter`
    // (toDefaultDashboard) -- with no dashboard visible (the stubbed bootstrap is 401/anonymous), that lands
    // on `catalog`; the acceptance-relevant fact is that it's never the admin-only route itself.
    'sends a standard (non-admin) user away from %s (AR-2.5)',
    async (path) => {
      const router = makeRouter(fakeSession({ isAuthenticated: true, isAdmin: false }));
      await router.push(path);
      expect(router.currentRoute.value.name).toBe('catalog');
    },
  );

  it.each(['/settings/users', '/settings/orphans', '/settings/client-ip', '/audit'])(
    'lets an Admin reach %s',
    async (path) => {
      const router = makeRouter(fakeSession({ isAuthenticated: true, isAdmin: true }));
      await router.push(path);
      expect(router.currentRoute.value.path).toBe(path);
    },
  );

  it('does not admin-gate /settings, /sites, /teams, /zones, /catalog, /lists, /profile', async () => {
    const router = makeRouter(fakeSession({ isAuthenticated: true, isAdmin: false }));
    for (const path of ['/settings', '/sites', '/teams', '/zones', '/catalog', '/lists', '/profile']) {
      await router.push(path);
      expect(router.currentRoute.value.path, path).toBe(path);
    }
  });

  it('routes every AR-1.4 URL to a named route (no unregistered route falls through to not-found)', async () => {
    // / and /dashboard redirect through the real session store (test/unit/routes.spec.ts covers those).
    const router = makeRouter(fakeSession({ isAuthenticated: true, isAdmin: true }));
    const urls = [
      '/dashboard/abc-123',
      '/dashboard/abc-123/edit',
      '/catalog',
      '/lists',
      '/sites',
      '/teams',
      '/zones',
      '/settings',
      '/settings/users',
      '/settings/users/usr-1',
      '/settings/orphans',
      '/settings/client-ip',
      '/profile',
      '/audit',
    ];
    for (const url of urls) {
      await router.push(url);
      expect(router.currentRoute.value.name, url).not.toBe('not-found');
    }
  });

  it('/rbac redirects to /settings/users', async () => {
    const router = makeRouter(fakeSession({ isAuthenticated: true, isAdmin: true }));
    await router.push('/rbac');
    expect(router.currentRoute.value.path).toBe('/settings/users');
  });
});
