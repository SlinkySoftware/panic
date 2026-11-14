/**
 * Typed Server client generated from the OpenAPI contract (AR-1.7).
 *
 *   const { data, error } = await api.GET('/version');
 *
 * Paths are relative to `/api/v1` (the spec's `servers[0].url`). Types come from
 * `src/api/generated/openapi.ts`, regenerated with `npm run gen:api` (a unit test fails when it is stale).
 * Transport (CSRF, request IDs, session expiry) is shared with the hand-written calls via `apiFetch`.
 */
import createClient from 'openapi-fetch';
import type { paths } from './generated/openapi';
import { ApiError, API_BASE, apiFetch, apiUrl } from './http';

export type { paths, components } from './generated/openapi';

export const api = createClient<paths>({
  baseUrl: apiUrl(API_BASE),
  fetch: apiFetch,
});

/** Unwrap an openapi-fetch result: return `data` or throw `ApiError`. */
export function unwrap<T>(result: { data?: T; error?: unknown; response: Response }): T {
  if (result.response.ok && result.data !== undefined) return result.data;
  const body =
    result.error && typeof result.error === 'object' && !Array.isArray(result.error)
      ? (result.error as Record<string, unknown>)
      : null;
  throw new ApiError(result.response.status, body, result.response.headers.get('X-Request-ID'));
}
