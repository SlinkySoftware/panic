/**
 * The URL prefix PANIC is served under (`PANIC_BASE_PATH`, e.g. `/panic`), read at run time so one build
 * serves every prefix.
 *
 * index.html carries `<base href="/">`; panic-web's nginx rewrites it to `<base href="/panic/">` for a
 * prefixed deployment (the dev server renders it directly). Assets are built with relative URLs, so the base
 * tag is the only place the prefix lives in the browser. Everything that builds an absolute app URL (API
 * calls, the router, links the browser navigates to) goes through this module.
 */

/** `''` at `/`, else `/panic` (no trailing slash). */
export function basePathFrom(href: string | null | undefined): string {
  if (!href) return '';
  try {
    return new URL(href, 'http://panic.invalid/').pathname.replace(/\/+$/, '');
  } catch {
    return '';
  }
}

/** This page's prefix, read once from the `<base>` element. */
export const BASE_PATH = basePathFrom(
  typeof document === 'undefined' ? null : document.querySelector('base')?.getAttribute('href'),
);

/** An absolute path inside PANIC: `appPath('/api/v1/export')` → `/panic/api/v1/export`. */
export function appPath(path: string, base: string = BASE_PATH): string {
  return `${base}${path.startsWith('/') ? path : `/${path}`}`;
}
