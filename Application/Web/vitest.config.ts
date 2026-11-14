import { fileURLToPath } from 'node:url';
import vue from '@vitejs/plugin-vue';
import { quasar, transformAssetUrls } from '@quasar/vite-plugin';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [vue({ template: { transformAssetUrls } }), quasar()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  test: {
    environment: 'jsdom',
    // jsdom needs an http(s) origin so relative /api/v1 URLs resolve (AR-1.6) and cookies work.
    environmentOptions: { jsdom: { url: 'http://localhost:8120/' } },
    include: ['test/unit/**/*.spec.ts'],
    restoreMocks: true,
  },
});
