import { defineConfig } from '@quasar/app-vite';
import type { Plugin } from 'vite';
import { buildDevProxy, loadProxyPaths } from './dev-proxy';

// AR-1.6: the SPA itself never knows the Server URL. It is only read here, by the dev proxy.
const serverUrl = process.env.PANIC_SERVER_URL ?? 'http://127.0.0.1:8121';

// Vite rejects requests whose Host header is not localhost or listed here (DNS-rebinding protection).
// Comma-separated; a leading dot allows all subdomains.
const allowedHosts = (process.env.PANIC_WEB_ALLOWED_HOSTS ?? '')
  .split(',')
  .map((h) => h.trim())
  .filter(Boolean);

// URL prefix (PANIC_BASE_PATH, e.g. /panic). One build serves every prefix: assets use relative URLs and
// index.html carries `<base href="/">`, which panic-web's nginx rewrites for a prefixed deployment
// (Build/scripts/gen_nginx_conf.py). The dev server serves under the prefix itself.
const basePath = (process.env.PANIC_BASE_PATH ?? '')
  .split('/')
  .filter(Boolean)
  .map((s) => `/${s}`)
  .join('');

// `<base href>` first in <head>, added after Vite's own URL rewriting (which would make "/" relative).
// The built file has exactly `<base href="/">`: panic-web's sub_filter matches that string.
const baseTag = (href: string): Plugin => ({
  name: 'panic-base-tag',
  transformIndexHtml: {
    order: 'post',
    handler: () => [{ tag: 'base', attrs: { href }, injectTo: 'head-prepend' }],
  },
});

export default defineConfig((ctx) => ({
  boot: ['theme', 'auth'],
  css: ['app.css'],
  extras: ['roboto-font', 'material-icons'],
  build: {
    target: { browser: ['es2022', 'firefox115', 'chrome115', 'safari14'], node: 'node22' },
    typescript: { strict: true, vueShim: true },
    vueRouterMode: 'history',
    distDir: 'dist/spa',
    // Dev: served under the prefix. Build: '/' here, made relative below (Quasar refuses a relative
    // publicPath in history mode; the router takes its base from <base href> at run time instead).
    publicPath: ctx.dev ? `${basePath}/` : '/',
    vitePlugins: [baseTag(ctx.dev ? `${basePath}/` : '/')],
    extendViteConf(viteConf) {
      if (!ctx.dev) viteConf.base = './';
      // Pre-bundle openapi-fetch so the dev server does not discover it mid-session through a lazy route.
      viteConf.optimizeDeps = {
        ...viteConf.optimizeDeps,
        include: [...(viteConf.optimizeDeps?.include ?? []), 'openapi-fetch'],
      };
    },
  },
  devServer: {
    host: '0.0.0.0',
    port: Number(process.env.PANIC_WEB_PORT ?? 8120),
    open: false,
    strictPort: true, // fail loudly on a port clash instead of drifting to another port
    allowedHosts,
    proxy: buildDevProxy(serverUrl, loadProxyPaths(), basePath),
  },
  framework: { config: { dark: 'auto' }, plugins: ['Notify', 'Dialog', 'LocalStorage'] },
}));
