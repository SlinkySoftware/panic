/**
 * Auth-provider and session calls (API.md §4.1; generated OpenAPI types, AR-1.7).
 *
 *   GET  /api/v1/auth/providers  -> {instance_name, local_enabled, ldap_enabled, oidc}
 *   POST /api/v1/auth/login      {username, password} -> 200 {me} | 401 {error_code: UNAUTHENTICATED}
 *   POST /api/v1/auth/logout     204
 *
 * `GET /auth/oidc/login?next=...` is a plain-redirect endpoint (not JSON, not under /api/v1): the login page
 * navigates the browser to it directly rather than fetching it.
 */
import { api, unwrap, type components } from './client';
import { resetCsrfToken, refreshCsrfToken, toApiError } from './http';

export type Profile = components['schemas']['Profile'];
export type ProvidersResponse = components['schemas']['ProvidersResponse'];
export type LoginRequest = components['schemas']['LoginRequestRequest'];

export async function fetchProviders(): Promise<ProvidersResponse> {
  return unwrap(await api.GET('/auth/providers'));
}

export async function login(credentials: LoginRequest): Promise<Profile> {
  // Always start with a fresh token: the cookie may belong to an expired session.
  resetCsrfToken();
  await refreshCsrfToken();
  const res = unwrap(await api.POST('/auth/login', { body: credentials }));
  resetCsrfToken(); // Django rotates the token on login
  return res.me;
}

export async function logout(): Promise<void> {
  try {
    const { response } = await api.POST('/auth/logout');
    if (!response.ok) throw await toApiError(response);
  } finally {
    resetCsrfToken();
  }
}

/** `GET /auth/oidc/login?next=...`: a real browser navigation, never fetched (API.md §4.1). */
export function oidcLoginUrl(next: string): string {
  return `/auth/oidc/login?next=${encodeURIComponent(next)}`;
}
