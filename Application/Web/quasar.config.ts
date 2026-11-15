import { defineConfig } from '@quasar/app-vite';
import { buildDevProxy } from './dev-proxy';

// AR-1.6: the SPA itself never knows the Server URL. It is only read here, by the dev proxy.
const serverUrl = process.env.PANIC_SERVER_URL ?? 'http://127.0.0.1:8121';

// Vite rejects requests whose Host header is not localhost or listed here (DNS-rebinding protection).
// Comma-separated; a leading dot allows all subdomains.
const allowedHosts = (process.env.PANIC_WEB_ALLOWED_HOSTS ?? '')
  .split(',')
  .map((h) => h.trim())
  .filter(Boolean);

export default defineConfig(() => ({
  boot: ['theme', 'auth'],
  css: ['app.css'],
  extras: ['roboto-font', 'material-icons'],
  build: {
    target: { browser: ['es2022', 'firefox115', 'chrome115', 'safari14'], node: 'node22' },
    typescript: { strict: true, vueShim: true },
    vueRouterMode: 'history',
    distDir: 'dist/spa',
    extendViteConf(viteConf) {
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
    proxy: buildDevProxy(serverUrl),
  },
  framework: { config: { dark: 'auto' }, plugins: ['Notify', 'Dialog', 'LocalStorage'] },
}));
