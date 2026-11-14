// @vitest-environment node
/**
 * AR-6.4 / API.md §9: the dev proxy is derived from proxy-paths.json and nothing else, matches it exactly, and
 * never proxies /metrics.
 */
import { mkdtempSync, readFileSync, writeFileSync } from 'node:fs';
import type { ClientRequest, IncomingMessage } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import {
  buildDevProxy,
  ensureRequestId,
  isAllowedApiPath,
  loadProxyPaths,
  PROXY_PATHS_FILE,
  type ProxyPaths,
} from '../../dev-proxy';

const RULE_KEY = '^/(api|auth)/';
const fileContents = JSON.parse(readFileSync(PROXY_PATHS_FILE, 'utf8')) as ProxyPaths & { $comment?: string };

function proxied(url: string): boolean {
  const rule = buildDevProxy('http://server.invalid')[RULE_KEY];
  return rule.bypass({ url } as IncomingMessage, undefined, rule) === undefined;
}

describe('proxy-paths.json (API.md §9)', () => {
  it('is the allow-list from API.md §9', () => {
    expect(fileContents.prefixes).toEqual([
      '/api/v1/ui/',
      '/api/v1/auth/',
      '/api/v1/me/',
      '/api/v1/dashboards/',
      '/api/v1/catalog/',
      '/api/v1/lists/',
      '/api/v1/sites/',
      '/api/v1/teams/',
      '/api/v1/zones/',
      '/api/v1/users/',
      '/api/v1/admin/',
      '/api/v1/launch/rdp/',
      '/auth/oidc/',
    ]);
    expect(fileContents.exact).toEqual([
      '/api/v1/me',
      '/api/v1/dashboards',
      '/api/v1/catalog',
      '/api/v1/lists',
      '/api/v1/sites',
      '/api/v1/teams',
      '/api/v1/zones',
      '/api/v1/users',
      '/api/v1/settings',
      '/api/v1/audit',
      '/api/v1/export',
      '/api/v1/health',
      '/api/v1/version',
    ]);
  });

  it('never mentions /metrics', () => {
    const all = [...fileContents.prefixes, ...fileContents.exact];
    expect(all.some((p) => p.includes('metrics'))).toBe(false);
  });

  it('every prefix ends in / and every exact path does not', () => {
    for (const p of fileContents.prefixes) expect(p.endsWith('/'), p).toBe(true);
    for (const p of fileContents.exact) expect(p.endsWith('/'), p).toBe(false);
  });

  it('has no duplicates', () => {
    const all = [...fileContents.prefixes, ...fileContents.exact];
    expect(new Set(all).size).toBe(all.length);
  });

  it('every path matches the API.md §9 shape', () => {
    const shape = /^\/(api\/v1|auth)\/[A-Za-z0-9_-]+(\/[A-Za-z0-9_-]+)*\/?$/;
    for (const p of [...fileContents.prefixes, ...fileContents.exact]) expect(p, p).toMatch(shape);
  });

  it('is what loadProxyPaths() returns (single source)', () => {
    expect(loadProxyPaths()).toEqual({ prefixes: fileContents.prefixes, exact: fileContents.exact });
  });
});

describe('buildDevProxy', () => {
  it('has exactly one rule, for /api/ and /auth/, targeting the configured Server', () => {
    const proxy = buildDevProxy('http://127.0.0.1:8230');
    expect(Object.keys(proxy)).toEqual([RULE_KEY]);
    expect(proxy[RULE_KEY].target).toBe('http://127.0.0.1:8230');
    expect(proxy[RULE_KEY].xfwd).toBe(true);
  });

  it('proxies every allow-listed prefix and exact path', () => {
    for (const p of fileContents.prefixes) {
      expect(proxied(p), p).toBe(true);
      expect(proxied(`${p}anything/below?x=1`), p).toBe(true);
    }
    for (const p of fileContents.exact) {
      expect(proxied(p), p).toBe(true);
      expect(proxied(`${p}/`), p).toBe(true);
      expect(proxied(`${p}?ready=1`), p).toBe(true);
    }
  });

  it('proxies nothing else under /api/ or /auth/ (404 at Web)', () => {
    const denied = [
      '/metrics',
      '/metrics/',
      '/api/v1/ui', // prefix without its trailing slash is not the prefix
      '/api/v1/uix/auth/me',
      '/api/v1/healthz',
      '/api/v1/health/extra',
      '/api/v1/version/1',
      '/api/v2/ui/auth/me',
      '/api/v1/',
      '/api/',
      '/auth/',
      '/auth/oidc',
      '/auth/callback',
    ];
    for (const url of denied) expect(proxied(url), url).toBe(false);
  });

  it('refuses path tricks that could reach a forbidden path through an allowed prefix', () => {
    const tricks = [
      '/api/v1/ui/../../metrics',
      '/api/v1/ui/./auth/me',
      '/api/v1/ui/%2e%2e/metrics',
      '/api/v1/ui/%2E%2E%2Fmetrics',
      '/api/v1/ui/..%2fmetrics',
      '/api/v1/ui//metrics',
      '/api/v1/ui/..\\metrics',
    ];
    for (const url of tricks) expect(proxied(url), url).toBe(false);
  });

  it('matches the allow-list exactly: a path is proxied iff proxy-paths.json allows it', () => {
    const candidates = [
      ...fileContents.prefixes.flatMap((p) => [p, `${p}x`, p.slice(0, -1)]),
      ...fileContents.exact.flatMap((p) => [p, `${p}/`, `${p}x`]),
      '/api/v1/admin',
      '/api/v1/users',
    ];
    for (const url of candidates) {
      const expected =
        fileContents.prefixes.some((p) => url.startsWith(p)) ||
        fileContents.exact.some((p) => url === p || url === `${p}/`);
      expect(proxied(url), url).toBe(expected);
    }
  });
});

describe('loadProxyPaths validation', () => {
  function withFile(contents: object): string {
    const dir = mkdtempSync(join(tmpdir(), 'panic-proxy-'));
    const file = join(dir, 'proxy-paths.json');
    writeFileSync(file, JSON.stringify(contents));
    return file;
  }

  it('rejects a /metrics entry', () => {
    expect(() => loadProxyPaths(withFile({ prefixes: ['/metrics/'], exact: [] }))).toThrow(/metrics/);
  });

  it('rejects a prefix not ending in /', () => {
    expect(() => loadProxyPaths(withFile({ prefixes: ['/api/v1/ui'], exact: [] }))).toThrow(/end in/);
  });

  it('rejects an exact path ending in /', () => {
    expect(() => loadProxyPaths(withFile({ prefixes: [], exact: ['/api/v1/health/'] }))).toThrow(/must not end/);
  });

  it('rejects a path outside /api/v1/ or /auth/', () => {
    expect(() => loadProxyPaths(withFile({ prefixes: ['/admin/'], exact: [] }))).toThrow(/shape/);
  });

  it('rejects duplicates', () => {
    expect(() => loadProxyPaths(withFile({ prefixes: ['/api/v1/ui/', '/api/v1/ui/'], exact: [] }))).toThrow(
      /duplicate/,
    );
  });

  it('denies /metrics even if the list were misconfigured', () => {
    expect(isAllowedApiPath('/metrics', { prefixes: ['/'], exact: [] })).toBe(false);
  });
});

describe('X-Request-ID', () => {
  function run(headers: Record<string, string>): string | undefined {
    let set: string | undefined;
    ensureRequestId({ setHeader: ((_n: string, v: string) => (set = v)) as unknown as ClientRequest['setHeader'] }, {
      headers,
    } as unknown as IncomingMessage);
    return set;
  }

  it('forwards the incoming id', () => {
    expect(run({ 'x-request-id': 'abc-123' })).toBe('abc-123');
  });

  it('generates one when absent', () => {
    expect(run({})).toMatch(/^[0-9a-f-]{36}$/);
  });
});
