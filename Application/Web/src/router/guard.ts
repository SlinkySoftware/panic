import type { RouteLocationNormalized, RouteLocationRaw } from 'vue-router';

/** What the guard needs from the session store (kept minimal so the guard is unit-testable). */
export interface SessionState {
  readonly isAuthenticated: boolean;
  readonly isAdmin: boolean;
  ensureLoaded(): Promise<unknown>;
}

/**
 * Only same-app paths are accepted as a post-login redirect target: no open redirect to another origin
 * (`//host/...`, `https://...`), no backslash tricks, and never back to `/login` itself.
 */
export function safeRedirect(target: unknown): string {
  const t: unknown = Array.isArray(target) ? target[0] : target;
  if (typeof t !== 'string' || !t.startsWith('/') || t.startsWith('//') || t.includes('\\')) return '/';
  if (t === '/login' || t.startsWith('/login?') || t.startsWith('/login#') || t.startsWith('/login/')) return '/';
  return t;
}

/** `next` (exactly this query param name, per this task's scope line). */
export function loginLocation(next: string): RouteLocationRaw {
  const target = safeRedirect(next);
  return target === '/' ? { name: 'login' } : { name: 'login', query: { next: target } };
}

/**
 * - Anonymous user on a protected route -> `/login?next=<where they were going>`.
 * - Signed-in user on `/login` -> the `next` target (or `/`, which itself redirects to the default dashboard).
 * - If Server cannot be asked (network error / 5xx), protected routes go to `/login`, which reports the problem
 *   when the user tries to sign in.
 * - A standard user on an Admin-only route (`meta.admin`: Users, Orphans, Client-IP diagnostics, Audit) is sent
 *   to `/` (AR-2.5: those screens require `GLOBAL_ADMIN`).
 */
export async function authGuard(to: RouteLocationNormalized, session: SessionState): Promise<true | RouteLocationRaw> {
  try {
    await session.ensureLoaded();
  } catch {
    return to.meta.public ? true : loginLocation(to.fullPath);
  }
  if (to.name === 'login') return session.isAuthenticated ? safeRedirect(to.query.next) : true;
  if (to.meta.public) return true;
  if (!session.isAuthenticated) return loginLocation(to.fullPath);
  if (to.meta.admin && !session.isAdmin) return { path: '/' };
  return true;
}
