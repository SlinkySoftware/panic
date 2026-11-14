/**
 * Dev-server proxy for the Quasar/Vite dev server (AR-1.6, AR-6.4, API.md §9).
 *
 * The allow-list has exactly one source: `proxy-paths.json`, which the prod nginx template
 * generator (a later task) also consumes. Allow-listed paths are proxied to Server; anything else
 * under `/api/` or `/auth/` is a 404 at Web, exactly like nginx. `/metrics` is never proxied.
 *
 * Kept out of `quasar.config.ts` so the unit tests can import it directly (test/unit/devProxy.spec.ts).
 */
import { randomUUID } from 'node:crypto';
import { readFileSync } from 'node:fs';
import type { ClientRequest, IncomingMessage } from 'node:http';
import { fileURLToPath } from 'node:url';
import type { ProxyOptions } from 'vite';

export interface ProxyPaths {
  prefixes: string[];
  exact: string[];
}

export const PROXY_PATHS_FILE = fileURLToPath(new URL('./proxy-paths.json', import.meta.url));

/** `/metrics` must never be proxied through Web (AR-6.4, API.md §9), whatever the file says. */
export const FORBIDDEN_PATHS = ['/metrics'] as const;

// API.md §9: `^/(api/v1|auth)/[A-Za-z0-9_-]+(/[A-Za-z0-9_-]+)*/?$`; prefixes end in `/`, exact paths do not.
const PATH_SHAPE = /^\/(api\/v1|auth)\/[A-Za-z0-9_-]+(\/[A-Za-z0-9_-]+)*\/?$/;

export function loadProxyPaths(file: string = PROXY_PATHS_FILE): ProxyPaths {
  const raw = JSON.parse(readFileSync(file, 'utf8')) as Partial<ProxyPaths>;
  const paths: ProxyPaths = { prefixes: raw.prefixes ?? [], exact: raw.exact ?? [] };
  const seen = new Set<string>();
  for (const p of paths.prefixes) {
    if (!PATH_SHAPE.test(p)) throw new Error(`proxy-paths.json: prefix '${p}' does not match the API.md §9 shape`);
    if (!p.endsWith('/')) throw new Error(`proxy-paths.json: prefix '${p}' must end in '/'`);
    if (seen.has(p)) throw new Error(`proxy-paths.json: duplicate entry '${p}'`);
    seen.add(p);
  }
  for (const p of paths.exact) {
    if (!PATH_SHAPE.test(p)) throw new Error(`proxy-paths.json: exact path '${p}' does not match the API.md §9 shape`);
    if (p.endsWith('/')) throw new Error(`proxy-paths.json: exact path '${p}' must not end in '/'`);
    if (seen.has(p)) throw new Error(`proxy-paths.json: duplicate entry '${p}'`);
    seen.add(p);
  }
  for (const p of [...paths.prefixes, ...paths.exact]) {
    if (FORBIDDEN_PATHS.some((f) => p === f || p.startsWith(`${f}/`) || f.startsWith(p))) {
      throw new Error(`proxy-paths.json: '${p}' would expose a forbidden path (AR-6.4: /metrics never proxied)`);
    }
  }
  return paths;
}

/**
 * True when `url` (path + optional query) may be proxied to Server.
 * Paths with dot-segments, encoded dots/slashes, backslashes, double slashes or empty segments are refused so a
 * request such as `/api/v1/ui/../admin/view-as` cannot smuggle a call through an allowed prefix, and `/metrics`
 * can never be reached through Web even if it were (wrongly) added to the allow-list.
 */
export function isAllowedApiPath(url: string, paths: ProxyPaths): boolean {
  const path = url.split('?')[0] ?? '';
  if (/(^|\/)\.\.?(\/|$)|%2e|%2f|%5c|\\|\/\//i.test(path)) return false;
  if (FORBIDDEN_PATHS.some((f) => path === f || path.startsWith(`${f}/`))) return false;
  return paths.prefixes.some((p) => path.startsWith(p)) || paths.exact.some((p) => path === p || path === `${p}/`);
}

/** AR-3.2: forward X-Request-ID, generating one when the browser did not send it. */
export function ensureRequestId(proxyReq: Pick<ClientRequest, 'setHeader'>, req: IncomingMessage): void {
  const incoming = req.headers['x-request-id'];
  const id = (Array.isArray(incoming) ? incoming[0] : incoming) ?? randomUUID();
  proxyReq.setHeader('X-Request-ID', id);
}

/**
 * One rule for both `/api/` and `/auth/`: allow-listed paths are proxied to Server, anything else is a 404 at
 * Web (like prod nginx). A single rule avoids depending on proxy-key ordering.
 */
export function buildDevProxy(
  serverUrl: string,
  paths: ProxyPaths = loadProxyPaths(),
): { '^/(api|auth)/': ProxyOptions & { target: string; bypass: NonNullable<ProxyOptions['bypass']> } } {
  return {
    '^/(api|auth)/': {
      target: serverUrl,
      changeOrigin: false,
      xfwd: true, // X-Forwarded-For / -Proto / -Host; no X-Real-IP (API.md §9)
      bypass: (req) => (isAllowedApiPath(req.url ?? '', paths) ? undefined : false),
      configure: (proxy) => {
        proxy.on('proxyReq', (proxyReq, req) => ensureRequestId(proxyReq, req));
      },
    },
  };
}
