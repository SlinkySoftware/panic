/**
 * Core HTTP layer for every Server call made by the SPA.
 *
 * - AR-1.6: only relative `/api/v1/...` and `/auth/...` URLs. `apiUrl()` resolves them against the page's own
 *   origin (needed because `Request` wants an absolute URL); the SPA never knows Server's address.
 * - Django session auth: cookies are sent with `credentials: 'same-origin'`.
 * - CSRF (AR-2.10, API.md §1): unsafe methods carry `X-CSRFToken` (cookie `panic_csrftoken`, else the token from
 *   `GET /api/v1/auth/csrf`). A `403 CSRF_FAILED` response refreshes the token and retries the request once.
 * - A `401` from any endpoint other than the auth endpoints is reported to the registered unauthorized handler (a
 *   boot file sends the user to `/login?next=...`); API.md's `401 UNAUTHENTICATED` means "no/expired session".
 */

export const API_BASE = '/api/v1';
export const CSRF_COOKIE = 'panic_csrftoken';
export const CSRF_HEADER = 'X-CSRFToken';
export const REQUEST_ID_HEADER = 'X-Request-ID';
const CSRF_PATH = `${API_BASE}/auth/csrf`;
const AUTH_PATH_PREFIX = `${API_BASE}/auth/`;
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', 'TRACE']);

/** Error envelope used by Server (API.md §3): `{error_code, detail, fields?, ...extra}`. */
export type ApiErrorBody = { error_code?: string; detail?: string; fields?: Record<string, string[]> } & Record<
  string,
  unknown
>;

export class ApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody | null;
  readonly requestId: string | null;

  constructor(status: number, body: ApiErrorBody | null, requestId: string | null) {
    super(ApiError.describe(status, body));
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.requestId = requestId;
  }

  /** `detail` if present, otherwise the field errors joined, otherwise the HTTP status. */
  static describe(status: number, body: ApiErrorBody | null): string {
    if (body && typeof body.detail === 'string') return body.detail;
    if (body?.fields) {
      const parts = Object.entries(body.fields).map(([k, v]) => `${k}: ${v.join(' ')}`);
      if (parts.length) return parts.join('; ');
    }
    return status === 0 ? 'Server unreachable' : `Request failed (HTTP ${status})`;
  }

  get errorCode(): string | null {
    return this.body?.error_code ?? null;
  }

  get fieldErrors(): Record<string, string[]> {
    return this.body?.fields ?? {};
  }
}

export function apiUrl(path: string): string {
  const p =
    path.startsWith(API_BASE) || path.startsWith('/auth/')
      ? path
      : `${API_BASE}${path.startsWith('/') ? '' : '/'}${path}`;
  return new URL(p, globalThis.location.href).toString();
}

export function readCookie(name: string): string | null {
  if (typeof document === 'undefined') return null;
  for (const part of document.cookie.split(';')) {
    const [k, ...rest] = part.trim().split('=');
    if (k === name) return decodeURIComponent(rest.join('='));
  }
  return null;
}

/**
 * RFC 4122 v4 UUID. `crypto.randomUUID` exists only in secure contexts (HTTPS or localhost), so
 * plain-HTTP access by hostname (the dev server) falls back to `getRandomValues`, which is always present.
 */
export function newRequestId(): string {
  const c = globalThis.crypto;
  if (typeof c.randomUUID === 'function') return c.randomUUID();
  const b = c.getRandomValues(new Uint8Array(16));
  b[6] = (b[6]! & 0x0f) | 0x40; // version 4
  b[8] = (b[8]! & 0x3f) | 0x80; // variant 10xx
  const h = Array.from(b, (x) => x.toString(16).padStart(2, '0')).join('');
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}

// ---------------------------------------------------------------------------------------------------- CSRF token

let cachedCsrfToken: string | null = null;
let csrfInFlight: Promise<string> | null = null;

/** Fetch a fresh token from Server (sets/rotates the `panic_csrftoken` cookie; API.md §4.1). */
export async function refreshCsrfToken(): Promise<string> {
  csrfInFlight ??= (async () => {
    try {
      const res = await fetch(
        new Request(apiUrl(CSRF_PATH), {
          credentials: 'same-origin',
          headers: { Accept: 'application/json', [REQUEST_ID_HEADER]: newRequestId() },
        }),
      );
      if (!res.ok) throw await toApiError(res);
      cachedCsrfToken = readCookie(CSRF_COOKIE);
      if (!cachedCsrfToken) throw new ApiError(res.status, { detail: 'No CSRF token returned' }, null);
      return cachedCsrfToken;
    } finally {
      csrfInFlight = null;
    }
  })();
  return csrfInFlight;
}

/** Cookie first (Django rotates it on login), then the cached value, then ask Server. */
export async function getCsrfToken(): Promise<string> {
  return readCookie(CSRF_COOKIE) ?? cachedCsrfToken ?? refreshCsrfToken();
}

/** Forget the cached token (Django rotates the token on login/logout). */
export function resetCsrfToken(): void {
  cachedCsrfToken = null;
}

// ------------------------------------------------------------------------------------------- unauthorized hook

type UnauthorizedHandler = (res: Response) => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export function setUnauthorizedHandler(handler: UnauthorizedHandler | null): void {
  unauthorizedHandler = handler;
}

// ------------------------------------------------------------------------------------------------------ fetch

async function isCsrfFailure(res: Response): Promise<boolean> {
  if (res.status !== 403) return false;
  try {
    const body = (await res.clone().json()) as ApiErrorBody;
    return body.error_code === 'CSRF_FAILED';
  } catch {
    return false;
  }
}

function prepare(request: Request, csrfToken: string | null): Request {
  const headers = new Headers(request.headers);
  if (!headers.has(REQUEST_ID_HEADER)) headers.set(REQUEST_ID_HEADER, newRequestId());
  if (!headers.has('Accept')) headers.set('Accept', 'application/json');
  if (csrfToken) headers.set(CSRF_HEADER, csrfToken);
  return new Request(request, { headers, credentials: 'same-origin' });
}

/**
 * fetch() for Server calls. Used as the `fetch` of the openapi-fetch client and by hand-written calls.
 * Returns the raw Response (callers decide how to treat non-2xx); network failures become `ApiError(0)`.
 */
export async function apiFetch(input: Request): Promise<Response> {
  const unsafe = !SAFE_METHODS.has(input.method.toUpperCase());
  const retryCopy = unsafe ? input.clone() : null;
  let res: Response;
  try {
    res = await fetch(prepare(input, unsafe ? await getCsrfToken() : null));
    if (retryCopy && (await isCsrfFailure(res))) {
      res = await fetch(prepare(retryCopy, await refreshCsrfToken()));
    }
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(0, { detail: `Server unreachable: ${e instanceof Error ? e.message : String(e)}` }, null);
  }
  const path = new URL(input.url).pathname;
  if (res.status === 401 && !path.startsWith(AUTH_PATH_PREFIX)) {
    unauthorizedHandler?.(res);
  }
  return res;
}

export async function toApiError(res: Response, requestId: string | null = null): Promise<ApiError> {
  let body: ApiErrorBody | null = null;
  try {
    const parsed: unknown = await res.clone().json();
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) body = parsed as ApiErrorBody;
  } catch {
    body = null;
  }
  return new ApiError(res.status, body, res.headers.get(REQUEST_ID_HEADER) ?? requestId);
}

/** JSON helper for hand-written calls: throws `ApiError` on non-2xx, returns `undefined` for 204. */
export async function requestJson<T>(
  method: string,
  path: string,
  body?: unknown,
  headers: Record<string, string> = {},
): Promise<T> {
  const requestId = newRequestId();
  const init: RequestInit = { method, headers: { ...headers, [REQUEST_ID_HEADER]: requestId } };
  if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { ...init.headers, 'Content-Type': 'application/json' };
  }
  const res = await apiFetch(new Request(apiUrl(path), init));
  if (!res.ok) throw await toApiError(res, requestId);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
