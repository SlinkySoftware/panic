/** CSRF header + one retry (this task's scope line), and the ApiError envelope shape (API.md §3). */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  apiFetch,
  apiUrl,
  ApiError,
  CSRF_HEADER,
  newRequestId,
  readCookie,
  resetCsrfToken,
  requestJson,
} from '@/api/http';

function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

describe('apiFetch / CSRF retry', () => {
  beforeEach(() => {
    resetCsrfToken();
    document.cookie = 'panic_csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sends the cookie token as X-CSRFToken on an unsafe method', async () => {
    document.cookie = 'panic_csrftoken=cookie-token; path=/';
    const seen: (string | null)[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((req: Request) => {
        seen.push(req.headers.get(CSRF_HEADER));
        return jsonResponse({ ok: true });
      }),
    );
    await apiFetch(new Request(apiUrl('/catalog'), { method: 'POST' }));
    expect(seen).toEqual(['cookie-token']);
  });

  it('on a 403 CSRF_FAILED, refreshes the token and retries exactly once', async () => {
    document.cookie = 'panic_csrftoken=stale-token; path=/';
    let calls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn((req: Request) => {
        calls += 1;
        const url = new URL(req.url).pathname;
        if (url.endsWith('/auth/csrf')) {
          document.cookie = 'panic_csrftoken=fresh-token; path=/';
          return new Response(null, { status: 204 });
        }
        if (req.headers.get(CSRF_HEADER) === 'fresh-token') return jsonResponse({ ok: true });
        return jsonResponse({ error_code: 'CSRF_FAILED', detail: 'CSRF Failed: Token missing.' }, 403);
      }),
    );
    const res = await apiFetch(new Request(apiUrl('/catalog'), { method: 'POST' }));
    expect(res.ok).toBe(true);
    expect(calls).toBe(3); // first attempt (403), csrf refresh, retry (200) -- never a second retry
  });

  it('does not retry a 403 that is not CSRF_FAILED', async () => {
    document.cookie = 'panic_csrftoken=token1; path=/';
    let calls = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        calls += 1;
        return jsonResponse({ error_code: 'PERMISSION_DENIED', detail: 'nope' }, 403);
      }),
    );
    const res = await apiFetch(new Request(apiUrl('/catalog'), { method: 'POST' }));
    expect(res.status).toBe(403);
    expect(calls).toBe(1);
  });

  it('never sends a CSRF header on a safe (GET) request', async () => {
    const seen: (string | null)[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn((req: Request) => {
        seen.push(req.headers.get(CSRF_HEADER));
        return jsonResponse({ ok: true });
      }),
    );
    await apiFetch(new Request(apiUrl('/catalog')));
    expect(seen).toEqual([null]);
  });

  it('ApiError.describe prefers detail, then fields, then the HTTP status', () => {
    expect(ApiError.describe(400, { detail: 'Bad.' })).toBe('Bad.');
    expect(ApiError.describe(400, { fields: { title: ['Required.'] } })).toBe('title: Required.');
    expect(ApiError.describe(500, null)).toBe('Request failed (HTTP 500)');
    expect(ApiError.describe(0, null)).toBe('Server unreachable');
  });

  it('requestJson throws ApiError with the error_code surfaced', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse({ error_code: 'NOT_FOUND', detail: 'Gone.' }, 404)),
    );
    await expect(requestJson('GET', '/catalog/x')).rejects.toMatchObject({ status: 404, message: 'Gone.' });
  });

  it('a network failure becomes ApiError(0)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        throw new TypeError('network down');
      }),
    );
    await expect(requestJson('GET', '/catalog')).rejects.toMatchObject({ status: 0 });
  });

  it('readCookie reads the named cookie only', () => {
    document.cookie = 'panic_csrftoken=abc; path=/';
    document.cookie = 'other=xyz; path=/';
    expect(readCookie('panic_csrftoken')).toBe('abc');
    expect(readCookie('missing')).toBeNull();
  });
});

describe('newRequestId', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('returns a v4 UUID without crypto.randomUUID (insecure context: plain HTTP by hostname)', () => {
    const real = globalThis.crypto;
    vi.stubGlobal('crypto', { getRandomValues: <T extends ArrayBufferView>(a: T) => real.getRandomValues(a) });
    const ids = new Set(Array.from({ length: 50 }, () => newRequestId()));
    expect(ids.size).toBe(50);
    for (const id of ids) expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  });
});
