// ESLint flat config: @eslint/js + typescript-eslint (type-aware) + eslint-plugin-vue, with Prettier owning
// formatting (eslint-config-prettier switches off conflicting rules; `npm run lint` also runs `prettier --check`).
import pluginVue from 'eslint-plugin-vue';
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript';
import prettierConfig from 'eslint-config-prettier/flat';
import globals from 'globals';

export default defineConfigWithVueTs(
  {
    ignores: [
      'dist/**',
      '.quasar/**',
      'node_modules/**',
      'src/api/generated/**',
      'test-results/**',
      'quasar.config.*.temporary.compiled*',
    ],
  },
  pluginVue.configs['flat/recommended'],
  vueTsConfigs.recommendedTypeChecked,
  {
    languageOptions: {
      globals: { ...globals.browser, ...globals.node },
    },
    rules: {
      'no-console': ['warn', { allow: ['info', 'warn', 'error'] }],
      'vue/multi-word-component-names': 'off',
      '@typescript-eslint/consistent-type-imports': ['error', { prefer: 'type-imports' }],
      '@typescript-eslint/no-floating-promises': 'error',
      // AR-1.7: Web never imports the Python contracts package.
      'no-restricted-imports': ['error', { patterns: ['*panic_common*'] }],
    },
  },
  {
    // Browser code: `process` does not exist at runtime in @quasar/app-vite 3 (use import.meta.env).
    files: ['src/**/*.{ts,vue}'],
    rules: {
      'no-restricted-globals': ['error', { name: 'process', message: 'Use import.meta.env in browser code.' }],
    },
  },
  {
    files: ['scripts/**/*.mjs', '*.config.*', 'dev-proxy.ts'],
    extends: [vueTsConfigs.disableTypeChecked],
  },
  prettierConfig,
);
